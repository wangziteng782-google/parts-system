"""把测试库的商品库对外展示配置同步到正式库。

只做三件事：
1. 补 product_variant_prices 缺失的两列：retail_invoice_company、retail_tax_rate；
2. 同步这两列在销售价行（supplier=''）上的数据；
3. 按正式库自己的采购报价类型回填销售价行的 external_price_fields，
   并重算 parts.display_price_min/max。

采购报价行（supplier<>''）的价格和字段一律不动。

用法：
    python jobs/sync_prod_ext_fields.py            # 预览
    python jobs/sync_prod_ext_fields.py --apply    # 执行
"""
import argparse
import os
import sys
from collections import Counter

import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parts_system.config.constants import DB_CONFIG  # noqa: E402
from parts_system.inquiry_sync import PROD_DB  # noqa: E402

PROD = dict(PROD_DB, cursorclass=pymysql.cursors.DictCursor)
LOCAL = dict(DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)

NEW_COLUMNS = [
    ("retail_invoice_company",
     "VARCHAR(100) NULL COMMENT '开票类型及单位，OA原文，如 昭道开专、吾爱开普'"),
    ("retail_tax_rate",
     "VARCHAR(20) NULL COMMENT '税率，OA原文，如 13、4'"),
]


def decide(has_special, has_general, has_no_tax):
    if has_special:
        return "special"
    if has_general:
        return "general"
    if has_no_tax:
        return "no_tax"
    return None


def ensure_columns(cur):
    cur.execute("SHOW COLUMNS FROM product_variant_prices")
    existing = {r["Field"] for r in cur.fetchall()}
    added = []
    for name, ddl in NEW_COLUMNS:
        if name in existing:
            continue
        cur.execute(f"ALTER TABLE product_variant_prices ADD COLUMN {name} {ddl}")
        added.append(name)
    cur.execute("SHOW FULL COLUMNS FROM product_variant_prices LIKE 'retail_price'")
    column = cur.fetchone()
    comment_ok = column and str(column.get("Comment") or "") == "销售价格"
    return added, comment_ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    src = pymysql.connect(**LOCAL)
    dst = pymysql.connect(**PROD)
    try:
        # 两库 part_id / variant_group_id 都是重新生成的，只能用 sku_code + 规格签名对齐
        sc = src.cursor()
        sc.execute("""
            SELECT p.sku_code,
                   GROUP_CONCAT(CONCAT(s.spec_name,':',s.spec_value)
                                ORDER BY s.spec_name SEPARATOR '|') AS sig,
                   v.retail_invoice_company, v.retail_tax_rate
              FROM product_variant_prices v
              JOIN parts p ON p.id=v.part_id
              JOIN product_variant_group_specs l
                ON l.part_id=v.part_id AND l.variant_group_id=v.variant_group_id
              JOIN product_variant_specs s ON s.id=l.spec_id
             WHERE p.pricing_mode=2 AND v.supplier=''
               AND (v.retail_invoice_company IS NOT NULL OR v.retail_tax_rate IS NOT NULL)
             GROUP BY p.sku_code, v.part_id, v.variant_group_id,
                      v.retail_invoice_company, v.retail_tax_rate""")
        src_invoice = {(r["sku_code"], r["sig"]): r for r in sc.fetchall()}

        dc = dst.cursor()
        dc.execute("SHOW COLUMNS FROM product_variant_prices")
        existing = {r["Field"] for r in dc.fetchall()}
        missing = [name for name, _ in NEW_COLUMNS if name not in existing]
        print("正式库缺失列：", missing or "无")

        # 正式库采购报价类型 → 决定销售价对外展示类型
        dc.execute("""
            SELECT p.id AS part_id, v.variant_group_id,
                   MAX(v.purchase_special_invoice > 0) AS has_special,
                   MAX(v.purchase_general_invoice > 0) AS has_general,
                   MAX(v.no_tax_price > 0) AS has_no_tax
              FROM product_variant_prices v
              JOIN parts p ON p.id=v.part_id
             WHERE p.pricing_mode=2 AND v.supplier<>''
             GROUP BY p.id, v.variant_group_id""")
        groups = {(r["part_id"], r["variant_group_id"]): r for r in dc.fetchall()}

        dc.execute("""
            SELECT v.id, v.part_id, v.variant_group_id, v.external_price_fields
              FROM product_variant_prices v
              JOIN parts p ON p.id=v.part_id
             WHERE p.pricing_mode=2 AND v.supplier=''""")
        sales = dc.fetchall()

        plan = []
        for row in sales:
            group = groups.get((row["part_id"], row["variant_group_id"]))
            if not group:
                continue
            target = decide(group["has_special"], group["has_general"], group["has_no_tax"])
            if target is None:
                continue
            plan.append((row, target))

        # 正式库 group 的规格签名 → 定位到正式库自己的 part_id / variant_group_id
        dc.execute("""
            SELECT p.sku_code, v.part_id, v.variant_group_id,
                   GROUP_CONCAT(CONCAT(s.spec_name,':',s.spec_value)
                                ORDER BY s.spec_name SEPARATOR '|') AS sig
              FROM product_variant_prices v
              JOIN parts p ON p.id=v.part_id
              JOIN product_variant_group_specs l
                ON l.part_id=v.part_id AND l.variant_group_id=v.variant_group_id
              JOIN product_variant_specs s ON s.id=l.spec_id
             WHERE p.pricing_mode=2 AND v.supplier=''
             GROUP BY p.sku_code, v.part_id, v.variant_group_id""")
        dst_groups = {(r["sku_code"], r["sig"]): (r["part_id"], r["variant_group_id"])
                      for r in dc.fetchall()}
        invoice_targets = [(key, src_invoice[key], dst_groups[key])
                           for key in src_invoice if key in dst_groups]

        print(f"销售价行 {len(sales)}，可判定 {len(plan)}，"
              f"需变更 {sum(1 for r, t in plan if (r['external_price_fields'] or '') != t)}")
        print("对外展示类型：", dict(Counter(t for _, t in plan)))
        print(f"待同步开票类型/税率数据：{len(invoice_targets)} 行"
              f"（测试库有值 {len(src_invoice)} 行，正式库匹配上 {len(invoice_targets)} 行）")

        if not args.apply:
            print("\n预览模式，未写入。")
            return

        added, comment_ok = ensure_columns(dc)
        print("已新增列：", added or "无")
        if not comment_ok:
            dc.execute(
                "ALTER TABLE product_variant_prices MODIFY COLUMN retail_price "
                "DECIMAL(14,2) NULL COMMENT '销售价格'"
            )
            print("已更新 retail_price 注释 -> 销售价格")

        dc.execute(
            "CREATE TABLE IF NOT EXISTS pvp_ext_fields_bak_20261126 "
            "AS SELECT id, external_price_fields, retail_invoice_company, retail_tax_rate "
            "FROM product_variant_prices"
        )
        synced = 0
        for _key, src_row, (part_id, group_id) in invoice_targets:
            dc.execute(
                """UPDATE product_variant_prices
                      SET retail_invoice_company=%s, retail_tax_rate=%s
                    WHERE part_id=%s AND variant_group_id=%s AND supplier=''""",
                (src_row["retail_invoice_company"], src_row["retail_tax_rate"],
                 part_id, group_id),
            )
            synced += dc.rowcount
        for row, target in plan:
            dc.execute(
                "UPDATE product_variant_prices SET external_price_fields=%s WHERE id=%s",
                (target, row["id"]),
            )
        dc.execute(
            """UPDATE parts p
                 JOIN (SELECT part_id, MIN(retail_price) AS mn, MAX(retail_price) AS mx
                         FROM product_variant_prices
                        WHERE supplier=''
                          AND external_price_fields IS NOT NULL AND external_price_fields<>''
                        GROUP BY part_id) t ON t.part_id=p.id
                  SET p.display_price_min=t.mn, p.display_price_max=t.mx
                WHERE p.pricing_mode=2"""
        )
        dc.execute(
            """UPDATE parts p
                 SET p.display_price_min=NULL, p.display_price_max=NULL
               WHERE p.pricing_mode=2
                 AND NOT EXISTS (SELECT 1 FROM product_variant_prices v
                                  WHERE v.part_id=p.id AND v.supplier=''
                                    AND v.external_price_fields IS NOT NULL
                                    AND v.external_price_fields<>'')"""
        )
        dst.commit()
        print(f"\n已写入正式库：开票类型/税率 {synced} 行，"
              f"对外展示类型 {len(plan)} 行。")
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    main()
