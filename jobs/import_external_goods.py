"""把外部商品库的数据导入产品库，按定价模式 2（人工维护销售价）落库。

聚合规则（同型号 = 1 个 SPU）：
    - 名称不同 → 名称作为规格维度，每个名称一个 SKU
    - 品牌不同 → 品牌作为规格维度，每个品牌一个 SKU
    - 名称、品牌都相同 → 同一个 SKU，价格按供应商合并（同供应商取最新一条）
    - 型号为空 → 每条单独成一个 SPU，规格值用商品名

上下架：组内有任一在售即上架，全部下架才下架。
幂等：sku_code = EXT-{组内最小外部 id}，已存在则跳过。

数据源二选一：
    --from-oa   直连 OA 库 yh_goods（推荐，不用 token、不分页）
    --file      JSON 文件（离线试跑用）

用法：
    python -m jobs.import_external_goods --from-oa --goods-type 2 --env test --dry-run
    python -m jobs.import_external_goods --from-oa --goods-type 2 --env test --limit 20
    python -m jobs.import_external_goods --from-oa --goods-type 2 --env test
    python -m jobs.import_external_goods --from-oa --goods-type 2 --env prod
    python -m jobs.import_external_goods --file data/ext_goods.json --env test
"""
import argparse
import json
import sys
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pymysql

from jobs._prod_db import describe, prod_config
from parts_system.config.constants import DB_CONFIG, PRODUCT_TYPE_VALUES
# 本地 .env 没有 OA_DB_*，用同步脚本里的那份连接配置
from parts_system.inquiry_sync import OA_DB

SPEC_NAME = "规格型号"
# 型号和名称都缺时规格值会落成空串，卡片上是个空标签，统一成默认规格
DEFAULT_SPEC_NAME = "规格"
DEFAULT_SPEC_VALUE = "默认"
DEFAULT_SUPPLIER = "未填供应商"

# 外部分类名 → 三级分类。去「类」后能直接命中的不用写，这里只放对不上但业务上能对位的
TYPE_ALIASES = {
    "钢带类": "钢带(轮)",
    "钢带轮类": "钢带(轮)",
    "风扇类/风幕机类": "风扇",
    "接触器/继电器类": "电气开关与继电器",
    "电源类": "电源类器件",
    "对讲": "无线对讲",
    "断电": "ARD电梯自动救援装置",
    "断电平层类": "ARD电梯自动救援装置",
    # 以下在三级分类里找不到对应，先留空，由人工归类
    "梯控类": None,
    "梯控": None,
    "补偿链类": None,
    "空调类": None,
    "卡扣类": None,
    "卡扣": None,
    "卡扣类-合1": None,
    "车禁摄像头/物联网摄像头类": None,
}

# goods_type：2=爆品，1=全品，0/空=其他
GOODS_TYPE_NAMES = {2: "爆品", 1: "全品"}

OA_GOODS_SQL = """
SELECT id, goods_type_name, goods_type, factory, goods_name, goods_spec,
       goods_unit, goods_price, is_goods_price_fee, is_goods_price_fee_name,
       quotation_type, quotation_type_name, invoice_company, tax_rate,
       warehouse, remark, supplier, supplier_id, names, names_id,
       purchase_price_has_tax, purchase_price, post_fee_purchase,
       is_on_sale, warranty_month, goods_images, create_time, update_time,
       fitting_size, air_vent, weight, tiered_pricing
 FROM yh_goods
 WHERE delete_time IS NULL
 {type_filter}
 ORDER BY id DESC
 {limit_clause}
"""


def load_from_oa(limit=None, goods_type=None):
    """直连 OA 库拉商品，等价于 /admin/Goods/list 接口的数据。"""
    config = dict(OA_DB)
    config.setdefault("cursorclass", pymysql.cursors.DictCursor)
    params = []
    type_filter = ""
    if goods_type is not None:
        type_filter = "AND goods_type = %s"
        params.append(goods_type)
    limit_clause = ""
    if limit:
        limit_clause = "LIMIT %s"
        params.append(limit)

    sql = OA_GOODS_SQL.format(type_filter=type_filter, limit_clause=limit_clause)
    conn = pymysql.connect(**config)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def connect(env: str):
    config = dict(prod_config()) if env == "prod" else dict(DB_CONFIG)
    config["charset"] = "utf8mb4"
    config["cursorclass"] = pymysql.cursors.DictCursor
    config.setdefault("connect_timeout", 10)
    return pymysql.connect(**config)


def dec(value):
    """外部金额字段转 Decimal，脏数据返回 None。"""
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def image_json(value):
    """外部通常给单个图片 URL，本地字段存 JSON 数组。"""
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("["):
        return text
    return json.dumps([text], ensure_ascii=False)


def resolve_product_type(names):
    """外部分类名多带「类」后缀，先查别名表，再去「类」后缀匹配，命不中留空交人工补。"""
    name = str(names or "").strip()
    if not name:
        return None
    if name in TYPE_ALIASES:
        return TYPE_ALIASES[name]
    if name in PRODUCT_TYPE_VALUES:
        return name
    if name.endswith("类") and name[:-1] in PRODUCT_TYPE_VALUES:
        return name[:-1]
    return None


def invoice_field(item) -> str:
    """invoice_company 决定含税价进专票还是普票。"""
    company = str(item.get("invoice_company") or "")
    if "普" in company:
        return "purchase_general_invoice"
    return "purchase_special_invoice"


NAME_SPEC = "名称"
BRAND_SPEC = "品牌"
TIER_SPEC = "阶梯价"
UNKNOWN_BRAND = "未标注"
UNKNOWN_TIER = "未标注"


def _clean(value) -> str:
    return str(value or "").strip()


def _most_common(values) -> str:
    """取出现次数最多的值；次数相同取先出现的（OA 按 id 倒序，先出现的是最新录入）。"""
    counts, order = {}, {}
    for index, value in enumerate(values):
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
        order.setdefault(value, index)
    if not counts:
        return ""
    return max(counts, key=lambda v: (counts[v], -order[v]))


def _build_remark(item) -> str:
    extras = []
    unit = _clean(item.get("goods_unit"))
    if unit:
        extras.append(f"单位：{unit}")
    if str(item.get("quotation_type", "")) == "1":
        extras.append("售价含税")
    # 0 是有效值，不能用 or "" 兜底，否则会被当空串
    if str(item.get("is_goods_price_fee", "")) == "0":
        extras.append("售价不含运")
    return "；".join(filter(None, [_clean(item.get("remark")), "，".join(extras)]))


def _warranty_text(value) -> str:
    """质保月数转销售端可读文本：0 → 无质保，其余 → X个月。"""
    if value is None or str(value).strip() == "":
        return ""
    text = str(value).strip()
    try:
        months = int(float(text))
    except ValueError:
        return text
    return "无质保" if months <= 0 else f"{months}个月"


def _build_technical_params(item) -> str:
    """OA 的安装尺寸写入技术参数，sales 详情会展示这一栏。"""
    fitting_size = _clean(item.get("fitting_size"))
    if not fitting_size:
        return ""
    # OA 原文可能已带「外形尺寸：」前缀，避免叠成「安装尺寸：外形尺寸：…」
    return fitting_size if "尺寸" in fitting_size else f"安装尺寸：{fitting_size}"


def import_spu(cur, rows: list) -> str:
    """同一型号聚合成一个 SPU，组内按名称/品牌/阶梯价拆成多个 SKU。

    - 型号相同、名称相同、品牌相同：一个 SKU，多条价格按供应商合并（同供应商取最新一条）
    - 型号相同、名称不同：名称作为规格，每个名称一个 SKU
    - 型号相同、品牌不同：品牌作为规格，每个品牌一个 SKU
    - 组内阶梯价（OA tiered_pricing）有多个不同值：阶梯价作为规格，每个阶梯一个 SKU
    - 型号为空：同名同品牌聚合成一个 SPU，规格值用阶梯价，没有阶梯价则用「默认」
    """
    if not rows:
        raise ValueError("没有可导入的数据")

    first = rows[0]
    goods_spec = _clean(first.get("goods_spec"))
    names, brands = [], []
    for row in rows:
        name = _clean(row.get("goods_name"))
        if not name:
            raise ValueError("goods_name 不能为空")
        if name not in names:
            names.append(name)
        brand = _clean(row.get("factory"))
        if brand and brand not in brands:
            brands.append(brand)

    # 幂等：同型号（取组内最小外部 id）已导入则跳过
    sku_code = f"EXT-{min(int(row.get('id') or 0) for row in rows)}"
    cur.execute("SELECT id FROM parts WHERE sku_code=%s LIMIT 1", (sku_code,))
    if cur.fetchone():
        return "skip"

    tiers = []
    for row in rows:
        tier = _clean(row.get("tiered_pricing"))
        if tier and tier not in tiers:
            tiers.append(tier)

    dims = []
    if len(names) > 1:
        dims.append(NAME_SPEC)
    if len(brands) > 1:
        dims.append(BRAND_SPEC)
    if len(tiers) > 1:
        dims.append(TIER_SPEC)

    skus: dict[tuple, list] = {}
    for row in rows:
        name = _clean(row.get("goods_name"))
        brand = _clean(row.get("factory")) or UNKNOWN_BRAND
        tier = _clean(row.get("tiered_pricing")) or UNKNOWN_TIER
        key = (
            name if NAME_SPEC in dims else "",
            brand if BRAND_SPEC in dims else "",
            tier if TIER_SPEC in dims else "",
        )
        skus.setdefault(key, []).append(row)

    product_type = None
    for row in rows:
        product_type = resolve_product_type(row.get("names"))
        if product_type:
            break
    if not product_type and str(first.get("names") or "").strip():
        print(f"  ! 型号 {goods_spec or '空'} 的分类「{first.get('names')}」没匹配到三级分类，已留空，需在 /goods 手动补")

    cur.execute(
        """INSERT INTO parts
               (sku_code, product_name, product_brand, model, product_type, warranty,
                shipping_origin, remark, technical_params, status, pricing_mode, variant_groups_initialized,
                modification_completed, key_part_images, filler, update_time_2)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,2,1,1,%s,'外部导入',NOW())""",
        (
            sku_code,
            _most_common([_clean(row.get("goods_name")) for row in rows]) or goods_spec,
            brands[0] if len(brands) == 1 else None,
            goods_spec or None,
            product_type or None,
            _warranty_text(first.get("warranty_month")) or None,
            _clean(first.get("warehouse")) or None,
            _build_remark(first) or None,
            _build_technical_params(first) or None,
            # 组内有任一在售即上架，全部下架才下架
            1 if any(str(row.get("is_on_sale", 1)) == "1" for row in rows) else 0,
            image_json(first.get("goods_images")),
        ),
    )
    part_id = cur.lastrowid

    spec_cache: dict[tuple, int] = {}

    def spec_id_for(spec_name: str, spec_value: str) -> int:
        key = (spec_name, spec_value)
        if key in spec_cache:
            return spec_cache[key]
        cur.execute(
            """INSERT INTO product_variant_specs (part_id, spec_name, spec_value, sort_order)
               VALUES (%s,%s,%s,0)""",
            (part_id, spec_name, spec_value),
        )
        spec_cache[key] = cur.lastrowid
        return spec_cache[key]

    sale_prices = []
    for (sku_name, sku_brand, sku_tier), sku_rows in skus.items():
        if dims:
            values = []
            if NAME_SPEC in dims:
                values.append((NAME_SPEC, sku_name or UNKNOWN_BRAND))
            if BRAND_SPEC in dims:
                values.append((BRAND_SPEC, sku_brand or UNKNOWN_BRAND))
            if TIER_SPEC in dims:
                values.append((TIER_SPEC, sku_tier or UNKNOWN_TIER))
        else:
            # 无型号且名称未参与拆分时，规格值会是空串，兜底成「规格 / 默认」
            spec_value = (goods_spec or sku_name).strip()
            values = [(SPEC_NAME, spec_value)] if spec_value else [(DEFAULT_SPEC_NAME, DEFAULT_SPEC_VALUE)]

        variant_group_id = uuid.uuid4().hex
        for sort_order, (spec_name, spec_value) in enumerate(values):
            cur.execute(
                """INSERT INTO product_variant_group_specs
                       (part_id, variant_group_id, spec_id, sort_order)
                   VALUES (%s,%s,%s,%s)""",
                (part_id, variant_group_id, spec_id_for(spec_name, spec_value), sort_order),
            )

        # 同一 SKU 下同供应商只保留最新一条报价（唯一键 part+variant_group+supplier）
        latest_by_supplier = {}
        for row in sku_rows:
            supplier = _clean(row.get("supplier")) or DEFAULT_SUPPLIER
            current = latest_by_supplier.get(supplier)
            if current is None or int(row.get("id") or 0) > int(current.get("id") or 0):
                latest_by_supplier[supplier] = row

        for supplier, row in latest_by_supplier.items():
            invoice_col = invoice_field(row)
            # 商品库商品的采购供应商报价默认不对外展示：external_price_fields 留空
            cur.execute(
                f"""INSERT INTO product_variant_prices
                       (part_id, variant_group_id, supplier, no_tax_price,
                        {invoice_col}, purchase_shipping, external_price_fields, is_default, warranty_time)
                   VALUES (%s,%s,%s,%s,%s,%s,NULL,1,%s)""",
                (
                    part_id,
                    variant_group_id,
                    supplier,
                    dec(row.get("purchase_price")),
                    dec(row.get("purchase_price_has_tax")),
                    dec(row.get("post_fee_purchase")),
                    _warranty_text(first.get("warranty_month")) or None,
                ),
            )

        # 销售价行：空供应商专用行，取该 SKU 最新一条外部售价
        newest = max(sku_rows, key=lambda row: int(row.get("id") or 0))
        sale_price = dec(newest.get("goods_price"))
        cur.execute(
            """INSERT INTO product_variant_prices
                   (part_id, variant_group_id, supplier, retail_price, is_default, warranty_time)
               VALUES (%s,%s,'',%s,0,%s)""",
            (part_id, variant_group_id, sale_price,
             _warranty_text(first.get("warranty_month")) or None),
        )
        if sale_price is not None:
            sale_prices.append(sale_price)

    cur.execute(
        "UPDATE parts SET display_price_min=%s, display_price_max=%s WHERE id=%s",
        (min(sale_prices) if sale_prices else None,
         max(sale_prices) if sale_prices else None,
         part_id),
    )
    return f"ok:{part_id}:{len(skus)}"


def main():
    parser = argparse.ArgumentParser(description="导入外部商品库数据（定价模式 2）")
    parser.add_argument("--file", help="外部商品 JSON 文件路径")
    parser.add_argument("--from-oa", action="store_true", help="直连 OA 库 yh_goods 拉数据")
    parser.add_argument("--goods-type", type=int, choices=(0, 1, 2), help="只导某类：2=爆品，1=全品")
    parser.add_argument("--env", choices=("test", "prod"), default="test")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 条，试跑用")
    parser.add_argument("--dry-run", action="store_true", help="只校验不写库")
    args = parser.parse_args()

    if not args.from_oa and not args.file:
        sys.exit("必须指定 --from-oa 或 --file")

    if args.from_oa:
        items = load_from_oa(args.limit, args.goods_type)
        source_label = "OA yh_goods" + (
            f" / {GOODS_TYPE_NAMES.get(args.goods_type, args.goods_type)}" if args.goods_type is not None else ""
        )
    else:
        source = Path(args.file)
        if not source.exists():
            sys.exit(f"文件不存在: {source}")
        items = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(items, dict):
            items = items.get("list") or items.get("data") or []
        if args.limit:
            items = items[:args.limit]
        source_label = str(source)

    if not isinstance(items, list) or not items:
        sys.exit("没有可导入的商品数据")

    print(f"数据源: {source_label}（{len(items)} 条）")
    print(f"目标库: {describe() if args.env == 'prod' else DB_CONFIG['host'] + '/' + DB_CONFIG['database']}")
    print(f"模式: {'dry-run' if args.dry_run else '写库'}")

    conn = connect(args.env)
    cur = conn.cursor()
    ok = skip = fail = sku_total = 0

    # 先按型号聚合，同型号合并成一个 SPU；无型号的按「名称+品牌」聚合
    groups: dict[str, list] = {}
    singles: dict[tuple, list] = {}
    for item in items:
        spec = str(item.get("goods_spec") or "").strip()
        if spec:
            groups.setdefault(spec, []).append(item)
        else:
            key = (
                str(item.get("goods_name") or "").strip(),
                str(item.get("factory") or "").strip(),
            )
            singles.setdefault(key, []).append(item)
    tasks = list(groups.values()) + list(singles.values())
    print(f"聚合后 SPU: {len(tasks)} 个（源数据 {len(items)} 条）")

    try:
        for index, rows in enumerate(tasks, start=1):
            label = str(rows[0].get("goods_spec") or rows[0].get("goods_name") or f"#{index}")[:40]
            try:
                result = import_spu(cur, rows)
            except Exception as exc:
                fail += 1
                print(f"  [{index}] {label} 失败: {type(exc).__name__}: {exc}")
                continue
            if result == "skip":
                skip += 1
                print(f"  [{index}] {label} 之前已导入，跳过")
            else:
                ok += 1
                _, pid, sku_count = result.split(":")
                sku_total += int(sku_count)
                print(f"  [{index}] {label} 导入成功 part_id={pid}，SKU {sku_count} 个")
        if args.dry_run:
            conn.rollback()
            print("\ndry-run：已回滚，库里没有写入")
        else:
            conn.commit()
            print("\n已提交")
    finally:
        cur.close()
        conn.close()

    print(f"结果：SPU 成功 {ok}，SKU {sku_total}，跳过 {skip}，失败 {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
