"""按采购报价实际落在哪类价格上，回填商品库商品销售价的对外展示类型。

规则（同一规格组合内，看采购报价哪个价格大于 0）：
    含专票价 > 0 → 含专票(special)
    否则含普票价 > 0 → 含普票(general)
    否则不含票价 > 0 → 不含票(no_tax)
    三类价格都为 0/空 → 留空（不对外展示）

用法：
    python jobs/backfill_ext_fields_by_purchase.py --env local           # 本地预览
    python jobs/backfill_ext_fields_by_purchase.py --env local --apply
    python jobs/backfill_ext_fields_by_purchase.py --env prod            # 正式库预览
    python jobs/backfill_ext_fields_by_purchase.py --env prod --apply
"""
import argparse
import os
import sys
from collections import Counter

import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parts_system.config.constants import DB_CONFIG  # noqa: E402
from parts_system.inquiry_sync import PROD_DB  # noqa: E402

CONFIGS = {"local": DB_CONFIG, "prod": PROD_DB}
COMMON = dict(cursorclass=pymysql.cursors.DictCursor)


def decide(row):
    if row["has_special"]:
        return "special"
    if row["has_general"]:
        return "general"
    if row["has_no_tax"]:
        return "no_tax"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=("local", "prod"), default="local")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = pymysql.connect(**CONFIGS[args.env], **COMMON)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id AS part_id, p.product_name, p.product_type,
                   v.variant_group_id,
                   MAX(v.purchase_special_invoice > 0) AS has_special,
                   MAX(v.purchase_general_invoice > 0) AS has_general,
                   MAX(v.no_tax_price > 0) AS has_no_tax
              FROM product_variant_prices v
              JOIN parts p ON p.id=v.part_id
             WHERE p.pricing_mode=2 AND v.supplier<>''
             GROUP BY p.id, v.variant_group_id""")
        groups = {(r["part_id"], r["variant_group_id"]): r for r in cur.fetchall()}

        cur.execute("""
            SELECT v.id, v.part_id, v.variant_group_id, v.retail_price,
                   v.external_price_fields, p.product_name, p.product_type
              FROM product_variant_prices v
              JOIN parts p ON p.id=v.part_id
             WHERE p.pricing_mode=2 AND v.supplier=''""")
        sales = cur.fetchall()

        plan = []
        no_group = 0
        for row in sales:
            group = groups.get((row["part_id"], row["variant_group_id"]))
            if group is None:
                no_group += 1
                continue
            target = decide(group)
            if target is None:
                continue
            plan.append((row, target, group))

        by_field = Counter(t for _, t, _ in plan)
        by_type = Counter((r.get("product_type") or "(空)", t) for r, t, _ in plan)
        changed = [p for p in plan if (p[0].get("external_price_fields") or "") != p[1]]

        print(f"[{args.env}] 销售价行 {len(sales)}，可判定 {len(plan)}，需变更 {len(changed)}，无采购报价 {no_group}")
        print("按类型：", dict(by_field))
        print("\n按产品分类（前 20）：")
        for (ptype, kind), c in by_type.most_common(20):
            print(f"  {ptype} {kind}: {c}")

        if args.env == "prod" and changed:
            print("\n变更样例（前 10）：")
            for row, target, group in changed[:10]:
                print(f"  part={row['part_id']} {row.get('product_name')} "
                      f"ref={row['retail_price']} -> {target}")

        if not args.apply:
            print("\n预览模式，未写入。")
            return

        cur.execute(
            "CREATE TABLE IF NOT EXISTS pvp_ext_fields_bak_20261126 "
            "AS SELECT id, external_price_fields FROM product_variant_prices"
        )
        for row, target, _group in plan:
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
        print(f"\n[{args.env}] 已写入 {len(plan)} 条销售价行，并重算展示价区间。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
