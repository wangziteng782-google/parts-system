"""按 OA 商品的含税属性回填商品库商品销售价的对外展示类型。

OA yh_goods.quotation_type：1=售价含税，0/空=不含税。
判定结果：含税 → 含专票(special)，不含税 → 不含票(no_tax)。

匹配方式：
1. parts.sku_code = EXT-{组内最小OA id}，用该 id 定位同型号组；
2. 按该销售价行所属规格组合的维度（发货仓/名称/品牌/阶梯价）筛 OA 行，
   同一型号拆成多仓、多品牌时不会张冠李戴；
3. 候选多于一条时按售价金额再筛，仍不唯一取最新 id；
4. 规格维度筛不出候选时退回组内最小 id 那一行。

用法：
    python jobs/backfill_ext_fields_from_oa.py           # 预览
    python jobs/backfill_ext_fields_from_oa.py --apply   # 写入
"""
import argparse
import os
import sys
from collections import Counter

import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parts_system.config.constants import DB_CONFIG  # noqa: E402
from parts_system.inquiry_sync import OA_DB as _OA_DB  # noqa: E402

OA_DB = dict(_OA_DB, cursorclass=pymysql.cursors.DictCursor)


def fetch_oa_rows():
    conn = pymysql.connect(**OA_DB)
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, goods_spec, goods_name, factory, goods_price,
                      quotation_type, warehouse, tiered_pricing
                 FROM yh_goods WHERE delete_time IS NULL"""
        )
        return cur.fetchall()
    finally:
        conn.close()


def quote_type_of(row) -> str:
    return "special" if str(row.get("quotation_type")) == "1" else "no_tax"


UNKNOWN = "未标注"
# 规格名 → OA 字段，导入时这四个维度会拆成不同 SKU
SPEC_TO_OA = {
    "发货仓": "warehouse",
    "名称": "goods_name",
    "品牌": "factory",
    "阶梯价": "tiered_pricing",
}


def match_rows(group, specs):
    """按规格组合的维度值筛出对应的 OA 行。"""
    matched = []
    for row in group:
        ok = True
        for spec_name, oa_field in SPEC_TO_OA.items():
            if spec_name not in specs:
                continue
            if (str(row.get(oa_field) or "").strip() or UNKNOWN) != specs[spec_name]:
                ok = False
                break
        if ok:
            matched.append(row)
    return matched


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际写入数据库")
    args = parser.parse_args()

    oa_rows = fetch_oa_rows()
    by_id = {int(r["id"]): r for r in oa_rows}
    by_spec = {}
    for r in oa_rows:
        spec = (r.get("goods_spec") or "").strip()
        if spec:
            by_spec.setdefault(spec, []).append(r)

    conn = pymysql.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, sku_code FROM parts
                WHERE pricing_mode=2 AND sku_code LIKE 'EXT-%'"""
        )
        parts = cur.fetchall()
        cur.execute(
            """SELECT id, part_id, variant_group_id, retail_price, external_price_fields
                 FROM product_variant_prices
                WHERE supplier='' AND part_id IN (SELECT id FROM parts WHERE pricing_mode=2)"""
        )
        sale_rows = cur.fetchall()
        cur.execute(
            """SELECT l.part_id, l.variant_group_id, s.spec_name, s.spec_value
                 FROM product_variant_group_specs l
                 JOIN product_variant_specs s ON s.id=l.spec_id
                WHERE l.part_id IN (SELECT id FROM parts WHERE pricing_mode=2)"""
        )
        spec_map = {}
        for r in cur.fetchall():
            spec_map.setdefault((r["part_id"], r["variant_group_id"]), {})[r["spec_name"]] = r["spec_value"]

        sales_by_part = {}
        for row in sale_rows:
            sales_by_part.setdefault(row["part_id"], []).append(row)

        plan = []
        no_base = 0
        unmatched_price = 0
        for part in parts:
            try:
                base_id = int(part["sku_code"].split("-", 1)[1])
            except (IndexError, ValueError):
                continue
            base_row = by_id.get(base_id)
            if not base_row:
                no_base += 1
                continue
            spec = (base_row.get("goods_spec") or "").strip()
            group = by_spec.get(spec, []) if spec else [base_row]
            for row in sales_by_part.get(part["id"], []):
                specs = spec_map.get((part["id"], row["variant_group_id"]), {})
                candidates = match_rows(group, specs) or group
                retail = row.get("retail_price")
                target_row = None
                if retail is not None:
                    for candidate in candidates:
                        price = candidate.get("goods_price")
                        if price is not None and float(price) == float(retail):
                            target_row = candidate
                            break
                if target_row is None:
                    unmatched_price += 1
                    # 同 SKU 只留最新一条报价，和导入取数逻辑一致
                    target_row = max(candidates, key=lambda r: int(r.get("id") or 0))
                plan.append((row, quote_type_of(target_row)))

        by_field = Counter(target for _, target in plan)
        changed = sum(1 for row, target in plan if (row.get("external_price_fields") or "") != target)
        print(f"销售价行 {len(sale_rows)}，可判定 {len(plan)}，需变更 {changed}")
        print("按类型：", dict(by_field))
        print(f"找不到 OA 组：{no_base} 个商品；金额没匹配到、退回最小 id 行：{unmatched_price} 行")

        print("\n抽样 12 条：")
        for row, target in plan[:12]:
            print(f"  [{target}] part={row['part_id']} retail={row.get('retail_price')}")

        if not args.apply:
            print("\n预览模式，未写入。")
            return

        cur.execute(
            "CREATE TABLE IF NOT EXISTS product_variant_prices_ext_fields_bak "
            "AS SELECT id, external_price_fields FROM product_variant_prices"
        )
        for row, target in plan:
            cur.execute(
                "UPDATE product_variant_prices SET external_price_fields=%s WHERE id=%s",
                (target, row["id"]),
            )
        cur.execute(
            """UPDATE parts p
                 JOIN (SELECT part_id, MIN(retail_price) AS mn, MAX(retail_price) AS mx
                         FROM product_variant_prices
                        WHERE supplier=''
                          AND external_price_fields IS NOT NULL AND external_price_fields<>''
                        GROUP BY part_id) t ON t.part_id=p.id
                  SET p.display_price_min=t.mn, p.display_price_max=t.mx
                WHERE p.pricing_mode=2"""
        )
        cur.execute(
            """UPDATE parts p
                 SET p.display_price_min=NULL, p.display_price_max=NULL
               WHERE p.pricing_mode=2
                 AND NOT EXISTS (SELECT 1 FROM product_variant_prices v
                                  WHERE v.part_id=p.id AND v.supplier=''
                                    AND v.external_price_fields IS NOT NULL
                                    AND v.external_price_fields<>'')"""
        )
        conn.commit()
        print(f"\n已写入 {len(plan)} 条销售价行，并重算展示价区间。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
