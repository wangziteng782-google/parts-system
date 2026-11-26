"""把 OA 商品库的「开票类型及单位」「税率」同步到销售价行。

匹配规则（与导入时的 SKU 拆分保持一致）：
    同型号 = 1 个 SPU，组内按 名称/品牌/阶梯价/发货仓 拆 SKU；
    每个 SKU 取 OA 里 id 最大（最新）那条记录的 invoice_company、tax_rate。
    规格里没有对应维度的不参与限制，比如只有「规格型号」的 SKU 取组内最新一条。

用法：
    python -m jobs.sync_retail_invoice_info --env test --dry-run
    python -m jobs.sync_retail_invoice_info --env test
    python -m jobs.sync_retail_invoice_info --env prod
"""
import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymysql

from jobs.import_external_goods import load_from_oa
from parts_system.config.constants import DB_CONFIG
from parts_system.inquiry_sync import OA_DB, PROD_DB

# 规格名 → OA 字段
SPEC_TO_FIELD = {
    "名称": "goods_name",
    "品牌": "factory",
    "阶梯价": "tiered_pricing",
    "发货仓": "warehouse",
}


def connect(env):
    cfg = dict(PROD_DB if env == "prod" else DB_CONFIG)
    cfg["charset"] = "utf8mb4"
    cfg["cursorclass"] = pymysql.cursors.DictCursor
    cfg["connect_timeout"] = 25
    return pymysql.connect(**cfg)


def load_oa_groups():
    """按导入规则把 OA 爆品聚合成 SPU → 记录列表。"""
    items = load_from_oa(None, 2)
    groups = {}
    for row in items:
        spec = str(row.get("goods_spec") or "").strip()
        if spec:
            groups.setdefault(("spec", spec), []).append(row)
        else:
            key = (
                "name",
                str(row.get("goods_name") or "").strip(),
                str(row.get("factory") or "").strip(),
            )
            groups.setdefault(key, []).append(row)
    return items, groups


def load_ext_skus(cur):
    """读库里的 EXT 商品及其规格组合，组装成 part_id + variant_group_id → 规格字典。"""
    cur.execute(
        """SELECT p.id AS part_id, p.sku_code, p.model, p.product_name,
                  g.variant_group_id, g.sort_order, s.spec_name, s.spec_value
             FROM parts p
             JOIN product_variant_group_specs g ON g.part_id = p.id
             JOIN product_variant_specs s ON s.id = g.spec_id
            WHERE p.sku_code LIKE 'EXT-%%'
            ORDER BY p.id, g.variant_group_id, g.sort_order"""
    )
    skus = {}
    for row in cur.fetchall():
        key = (row["part_id"], row["variant_group_id"])
        item = skus.setdefault(
            key,
            {
                "part_id": row["part_id"],
                "variant_group_id": row["variant_group_id"],
                "sku_code": row["sku_code"],
                "model": row["model"],
                "product_name": row["product_name"],
                "specs": {},
            },
        )
        item["specs"][row["spec_name"]] = row["spec_value"]
    return skus


def pick_latest(rows, specs):
    """按 SKU 规格过滤组内记录，取 id 最大的一条。"""
    candidates = []
    for row in rows:
        ok = True
        for spec_name, spec_value in specs.items():
            field = SPEC_TO_FIELD.get(spec_name)
            if not field:
                continue
            value = str(spec_value or "").strip()
            # 导入时缺值会落成「未标注」，这类占位不参与匹配
            if value in ("", "未标注"):
                continue
            if str(row.get(field) or "").strip() != value:
                ok = False
                break
        if ok:
            candidates.append(row)
    if not candidates:
        return None
    return max(candidates, key=lambda r: int(r.get("id") or 0))


def main():
    parser = argparse.ArgumentParser(description="同步 OA 开票类型及单位、税率到销售价行")
    parser.add_argument("--env", choices=("test", "prod"), default="test")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    items, groups = load_oa_groups()
    print(f"OA 爆品 {len(items)} 条，聚合 {len(groups)} 个 SPU")

    conn = connect(args.env)
    cur = conn.cursor()
    print(f"目标库 {conn.get_host_info()} / {args.env}")

    skus = load_ext_skus(cur)
    print(f"库里 EXT 商品 SKU {len(skus)} 个")

    plans = []
    unmatched = []
    for (part_id, group_id), info in skus.items():
        model = str(info["model"] or "").strip()
        if model:
            rows = groups.get(("spec", model))
        else:
            rows = groups.get(
                ("name", str(info["product_name"] or "").strip(),
                 ""),
            )
            if rows is None:
                # 无型号的聚合键带品牌，这里放宽：同名的所有组
                rows = []
                for key, value in groups.items():
                    if key[0] == "name" and key[1] == str(info["product_name"] or "").strip():
                        rows.extend(value)
        if not rows:
            unmatched.append(info)
            continue
        hit = pick_latest(rows, info["specs"])
        if hit is None:
            unmatched.append(info)
            continue
        plans.append(
            {
                "part_id": part_id,
                "variant_group_id": group_id,
                "sku_code": info["sku_code"],
                "model": model,
                "oa_id": hit.get("id"),
                "retail_invoice_company": (str(hit.get("invoice_company") or "").strip() or None),
                "retail_tax_rate": (str(hit.get("tax_rate") or "").strip() or None),
            }
        )

    print(f"匹配成功 {len(plans)} 个 SKU，未匹配 {len(unmatched)} 个")
    filled = [p for p in plans if p["retail_invoice_company"] or p["retail_tax_rate"]]
    print(f"其中 OA 有值可写入的 {len(filled)} 个")

    if unmatched:
        print("\n未匹配示例（前 5 个）:")
        for info in unmatched[:5]:
            print(f"   {info['sku_code']} {info['model']} 规格={info['specs']}")

    if args.dry_run:
        print("\n预览（前 10 条）:")
        for p in filled[:10]:
            print(
                f"   {p['sku_code']} {p['model']} <- OA#{p['oa_id']} "
                f"开票={p['retail_invoice_company']!r} 税率={p['retail_tax_rate']!r}"
            )
        print("[dry-run] 未写入")
        conn.close()
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / "tmp" / f"backup_retail_invoice_{args.env}_{stamp}.csv"
    backup.parent.mkdir(exist_ok=True)
    with backup.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(plans[0].keys()) if plans else ["part_id"])
        writer.writeheader()
        writer.writerows(plans)
    print(f"匹配结果已备份 -> {backup}")

    updated = 0
    for p in filled:
        cur.execute(
            """UPDATE product_variant_prices
                  SET retail_invoice_company=%s, retail_tax_rate=%s
                WHERE part_id=%s AND variant_group_id=%s AND supplier=''""",
            (
                p["retail_invoice_company"],
                p["retail_tax_rate"],
                p["part_id"],
                p["variant_group_id"],
            ),
        )
        updated += cur.rowcount
    conn.commit()
    print(f"更新销售价行 {updated} 行")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
