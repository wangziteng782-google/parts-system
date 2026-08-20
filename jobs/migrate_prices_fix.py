#!/usr/bin/env python
"""补充处理：税率0%价格同步 + 单供应商规格对外展示字段。

用途：
    migrate_supplier_prices.py 的后续补充：
    1. 税率0%的供应商，含税价应等于不含税价（之前跳过没算）
    2. 同规格只有一个供应商时，自动设置 external_price_fields 对外展示所有存在的价格

用法：
    python jobs/migrate_prices_fix.py --dry-run   # 预览
    python jobs/migrate_prices_fix.py --execute   # 正式执行
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import pymysql

# 复用已有函数
sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate_supplier_prices import parse_tax_point, parts_db_config, oa_db_config  # noqa


def match_supplier_tax(cursor, supplier_name: str) -> dict | None:
    """查询供应商税率"""
    if not supplier_name:
        return None
    cursor.execute(
        """SELECT s.id,
                  MAX(d.is_special_invoice) as is_special_invoice,
                  MAX(d.is_normal_invoice) as is_normal_invoice,
                  GROUP_CONCAT(DISTINCT CASE WHEN d.special_tax_point > '' THEN d.special_tax_point END) as special_tax_point,
                  GROUP_CONCAT(DISTINCT CASE WHEN d.normal_tax_point > '' THEN d.normal_tax_point END) as normal_tax_point
           FROM yh_supplier s
           LEFT JOIN yh_supplier_detail d ON s.id = d.supplier_id AND d.delete_time IS NULL
           WHERE s.supplier_name = %s AND s.delete_time IS NULL
           GROUP BY s.id
           LIMIT 1""",
        (supplier_name,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    def first_tax(key: str) -> float | None:
        val = row.get(key)
        return parse_tax_point(val.split(",")[0]) if val else None

    return {
        "is_special": bool(row["is_special_invoice"]),
        "is_normal": bool(row["is_normal_invoice"]),
        "special_tax": first_tax("special_tax_point"),
        "normal_tax": first_tax("normal_tax_point"),
    }


def build_external_fields(no_tax, special, normal) -> str | None:
    """根据存在的价格构建 external_price_fields"""
    fields = []
    if no_tax is not None and no_tax != 0:
        fields.append("no_tax")
    if special is not None and special != 0:
        fields.append("special")
    if normal is not None and normal != 0:
        fields.append("general")
    return ",".join(fields) if fields else None


def main() -> int:
    parser = argparse.ArgumentParser(description="补充处理价格")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        print("请指定 --dry-run 或 --execute")
        return 1

    parts_conn = pymysql.connect(**parts_db_config(), cursorclass=pymysql.cursors.DictCursor)
    oa_conn = pymysql.connect(**oa_db_config(), cursorclass=pymysql.cursors.DictCursor)
    parts_conn.autocommit(False)

    try:
        # === 任务1：税率0% → 含税价=不含税价 ===
        with parts_conn.cursor() as cur:
            cur.execute("""SELECT id, supplier, no_tax_price, purchase_special_invoice, purchase_general_invoice
                           FROM product_variant_prices
                           WHERE no_tax_price IS NOT NULL AND no_tax_price != 0""")
            records = cur.fetchall()

        tax_zero_updates = []

        for record in records:
            with oa_conn.cursor() as cur:
                supplier = match_supplier_tax(cur, record["supplier"])
            if not supplier:
                continue

            no_tax = float(record["no_tax_price"])
            cur_special = float(record["purchase_special_invoice"]) if record["purchase_special_invoice"] else None
            cur_normal = float(record["purchase_general_invoice"]) if record["purchase_general_invoice"] else None

            # 税率0%的专票：含税价=不含税价
            new_special = no_tax if (supplier["is_special"] and supplier["special_tax"] == 0 and cur_special != no_tax) else cur_special
            # 税率0%的普票：含税价=不含税价
            new_normal = no_tax if (supplier["is_normal"] and supplier["normal_tax"] == 0 and cur_normal != no_tax) else cur_normal

            if new_special != cur_special or new_normal != cur_normal:
                tax_zero_updates.append({"id": record["id"], "special": new_special, "normal": new_normal})

        print(f"任务1 - 税率0%价格同步: {len(tax_zero_updates)} 条需要更新")

        # === 任务2：单供应商规格设置 external_price_fields ===
        with parts_conn.cursor() as cur:
            # 找出只有一个供应商的 variant_group_id
            cur.execute("""SELECT variant_group_id, COUNT(DISTINCT supplier) as cnt
                           FROM product_variant_prices
                           GROUP BY variant_group_id
                           HAVING cnt = 1""")
            single_specs = [row["variant_group_id"] for row in cur.fetchall()]

        external_updates = []

        if single_specs:
            placeholders = ",".join(["%s"] * len(single_specs))
            with parts_conn.cursor() as cur:
                cur.execute(
                    f"""SELECT id, no_tax_price, purchase_special_invoice, purchase_general_invoice, external_price_fields
                        FROM product_variant_prices
                        WHERE variant_group_id IN ({placeholders})""",
                    tuple(single_specs),
                )
                records = cur.fetchall()

            for record in records:
                no_tax = float(record["no_tax_price"]) if record["no_tax_price"] else None
                special = float(record["purchase_special_invoice"]) if record["purchase_special_invoice"] and record["purchase_special_invoice"] != 0 else None
                normal = float(record["purchase_general_invoice"]) if record["purchase_general_invoice"] and record["purchase_general_invoice"] != 0 else None

                new_fields = build_external_fields(no_tax, special, normal)
                if new_fields and new_fields != record["external_price_fields"]:
                    external_updates.append((new_fields, record["id"]))

        print(f"任务2 - 单供应商规格对外展示: {len(external_updates)} 条需要更新")

        # === 执行写入 ===
        if args.execute:
            with parts_conn.cursor() as cur:
                for item in tax_zero_updates:
                    cur.execute(
                        """UPDATE product_variant_prices
                           SET purchase_special_invoice = %s,
                               purchase_general_invoice = %s
                           WHERE id = %s""",
                        (item["special"], item["normal"], item["id"]),
                    )
                for item in external_updates:
                    cur.execute(
                        "UPDATE product_variant_prices SET external_price_fields = %s WHERE id = %s",
                        (item[0], item[1]),
                    )
            parts_conn.commit()
            print("数据库已更新")
        else:
            print("（dry-run 模式，未写入）")

    finally:
        parts_conn.close()
        oa_conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
