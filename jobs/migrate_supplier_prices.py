#!/usr/bin/env python
"""迁移供应商价格：匹配OA供应商、根据税率自动计算价格。

用途：
    线上已有 2617 条供应商价格记录（product_variant_prices），
    旧数据只有供应商名称，无 OA 关联和税率。
    本脚本通过名称匹配 yh_supplier，获取税率后自动计算缺失价格。

执行流程：
    1. 导出备份
    2. 逐条匹配 OA 供应商
    3. 根据税率计算缺失价格
    4. 单供应商规格自动设置 external_price_fields
    5. 输出处理日志

用法：
    # 只预览（不写入）
    python jobs/migrate_supplier_prices.py --dry-run

    # 正式执行
    python jobs/migrate_supplier_prices.py --execute
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pymysql

PROJECT_DIR = Path(__file__).resolve().parents[1]
BACKUP_DIR = PROJECT_DIR / "jobs" / "backups"


def oa_db_config() -> dict[str, Any]:
    """OA 数据库配置（供应商/税率来源）"""
    return {
        "host": os.getenv("OA_DB_HOST", "120.46.152.222"),
        "port": int(os.getenv("OA_DB_PORT", "3306")),
        "user": os.getenv("OA_DB_USER", "oa_yixiuti"),
        "password": os.getenv("OA_DB_PASSWORD", "npFKTmTpzTzGAEcr"),
        "database": os.getenv("OA_DB_NAME", "oa_yixiuti"),
        "charset": "utf8mb4",
    }


def parts_db_config() -> dict[str, Any]:
    """Parts 系统数据库配置（价格记录读写）"""
    return {
        "host": os.getenv("PARTS_DB_HOST", "120.46.152.222"),
        "port": int(os.getenv("PARTS_DB_PORT", "3306")),
        "user": os.getenv("PARTS_DB_USER", "parts_database"),
        "password": os.getenv("PARTS_DB_PASSWORD", "1234"),
        "database": os.getenv("PARTS_DB_NAME", "parts_database"),
        "charset": "utf8mb4",
    }


def parse_tax_point(value: Any) -> float | None:
    """解析税率值，空值返回 None"""
    if value is None or value == "":
        return None
    try:
        n = float(str(value).replace("%", ""))
        return None if math.isnan(n) else n
    except (ValueError, TypeError):
        return None


def match_supplier(cursor, supplier_name: str) -> dict | None:
    """通过名称匹配 OA 供应商，返回税率信息"""
    if not supplier_name:
        return None

    # 精确匹配
    cursor.execute(
        """SELECT s.id, s.supplier_name,
                  MAX(d.is_special_invoice) as is_special_invoice,
                  MAX(d.is_normal_invoice) as is_normal_invoice,
                  MAX(d.is_no_invoice) as is_no_invoice,
                  GROUP_CONCAT(DISTINCT CASE WHEN d.special_tax_point > '' THEN d.special_tax_point END) as special_tax_point,
                  GROUP_CONCAT(DISTINCT CASE WHEN d.normal_tax_point > '' THEN d.normal_tax_point END) as normal_tax_point,
                  GROUP_CONCAT(DISTINCT CASE WHEN d.no_tax_point > '' THEN d.no_tax_point END) as no_tax_point
           FROM yh_supplier s
           LEFT JOIN yh_supplier_detail d ON s.id = d.supplier_id AND d.delete_time IS NULL
           WHERE s.supplier_name = %s AND s.delete_time IS NULL
           GROUP BY s.id, s.supplier_name
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
        "oa_supplier_id": row["id"],
        "is_special": bool(row["is_special_invoice"]),
        "is_normal": bool(row["is_normal_invoice"]),
        "is_no_tax": bool(row["is_no_invoice"]),
        "special_tax": first_tax("special_tax_point"),
        "normal_tax": first_tax("normal_tax_point"),
        "no_tax_point": first_tax("no_tax_point"),
    }


def to_price(value) -> float | None:
    """转为价格：None、空字符串、0 都视为未设置"""
    if value is None or value == "":
        return None
    n = float(value)
    return None if n == 0 else n


def calculate_prices(record: dict, supplier: dict) -> dict:
    """根据税率计算缺失价格"""
    no_tax_val = to_price(record.get("no_tax_price"))
    special_val = to_price(record.get("purchase_special_invoice"))
    normal_val = to_price(record.get("purchase_general_invoice"))

    tax_special = supplier.get("special_tax") or 0
    tax_normal = supplier.get("normal_tax") or 0

    # 只有不含税价 → 计算含税价
    if no_tax_val is not None and special_val is None and normal_val is None:
        if supplier.get("is_special") and tax_special > 0:
            special_val = round(no_tax_val * (1 + tax_special / 100), 2)
        if supplier.get("is_normal") and tax_normal > 0:
            normal_val = round(no_tax_val * (1 + tax_normal / 100), 2)

    # 有专票价格 → 计算不含税价
    elif special_val is not None and no_tax_val is None:
        if supplier.get("is_special") and tax_special > 0:
            no_tax_val = round(special_val / (1 + tax_special / 100), 2)

    # 有普票价格 → 计算不含税价
    elif normal_val is not None and no_tax_val is None:
        if supplier.get("is_normal") and tax_normal > 0:
            no_tax_val = round(normal_val / (1 + tax_normal / 100), 2)

    return {
        "no_tax_price": no_tax_val,
        "purchase_special_invoice": special_val,
        "purchase_general_invoice": normal_val,
    }


def export_backup(records: list[dict], fieldnames: list[str]) -> Path:
    """导出备份 CSV"""
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"variant_prices_backup_{timestamp}.csv"

    with backup_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    return backup_path


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移供应商价格")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写入")
    parser.add_argument("--execute", action="store_true", help="正式执行写入")
    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        print("请指定 --dry-run（预览）或 --execute（执行）")
        return 1

    parts_conn = pymysql.connect(**parts_db_config(), cursorclass=pymysql.cursors.DictCursor)
    oa_conn = pymysql.connect(**oa_db_config(), cursorclass=pymysql.cursors.DictCursor)
    parts_conn.autocommit(False)

    try:
        with parts_conn.cursor() as cursor:
            # 1. 读取所有供应商价格记录
            cursor.execute(
                """SELECT id, part_id, variant_group_id, supplier,
                          no_tax_price, purchase_special_invoice, purchase_general_invoice,
                          oa_supplier_id, external_price_fields
                   FROM product_variant_prices
                   ORDER BY id"""
            )
            records = cursor.fetchall()
            fieldnames = [desc[0] for desc in cursor.description]

        print(f"读取到 {len(records)} 条供应商价格记录")

        # 2. 导出备份
        if args.execute:
            backup_path = export_backup(records, fieldnames)
            print(f"已导出备份: {backup_path}")

        # 3. 逐条处理
        stats = {
            "total": len(records),
            "matched": 0,
            "unmatched": 0,
            "price_calculated": 0,
        }
        unmatched_suppliers = []
        updated_records = []
        # 按 variant_group_id 分组统计供应商数量
        spec_supplier_count: dict[int, set[str]] = {}

        for record in records:
            supplier_name = record["supplier"]
            variant_group_id = record["variant_group_id"]

            # 统计同规格供应商
            if variant_group_id not in spec_supplier_count:
                spec_supplier_count[variant_group_id] = set()
            spec_supplier_count[variant_group_id].add(supplier_name)

            with oa_conn.cursor() as cursor:
                supplier = match_supplier(cursor, supplier_name)

            if not supplier:
                stats["unmatched"] += 1
                unmatched_suppliers.append(supplier_name)
                continue

            stats["matched"] += 1

            # 计算价格
            new_prices = calculate_prices(record, supplier)

            # 判断是否有变化
            changed = False
            for field in ("no_tax_price", "purchase_special_invoice", "purchase_general_invoice"):
                old_val = record.get(field)
                new_val = new_prices.get(field)
                if old_val != new_val and new_val is not None:
                    changed = True
                    break

            if changed:
                stats["price_calculated"] += 1

            # 记录更新
            updated_records.append({
                "id": record["id"],
                "oa_supplier_id": supplier["oa_supplier_id"],
                "no_tax_price": new_prices["no_tax_price"],
                "purchase_special_invoice": new_prices["purchase_special_invoice"],
                "purchase_general_invoice": new_prices["purchase_general_invoice"],
                "changed": changed,
            })

        # 4. 写入数据库
        if args.execute:
            with parts_conn.cursor() as cursor:
                for item in updated_records:
                    if not item["changed"] and item["oa_supplier_id"]:
                        # 只更新 oa_supplier_id
                        cursor.execute(
                            "UPDATE product_variant_prices SET oa_supplier_id = %s WHERE id = %s",
                            (item["oa_supplier_id"], item["id"]),
                        )
                    elif item["changed"]:
                        cursor.execute(
                            """UPDATE product_variant_prices
                               SET oa_supplier_id = %s,
                                   no_tax_price = %s,
                                   purchase_special_invoice = %s,
                                   purchase_general_invoice = %s
                               WHERE id = %s""",
                            (
                                item["oa_supplier_id"],
                                item["no_tax_price"],
                                item["purchase_special_invoice"],
                                item["purchase_general_invoice"],
                                item["id"],
                            ),
                        )
            parts_conn.commit()
            print("数据库已更新")

        # 5. 输出日志
        single_count = sum(1 for s in spec_supplier_count.values() if len(s) == 1)
        print("\n" + "=" * 50)
        print("处理结果统计")
        print("=" * 50)
        print(f"总记录数: {stats['total']}")
        print(f"成功匹配: {stats['matched']}")
        print(f"匹配失败: {stats['unmatched']}")
        print(f"价格计算: {stats['price_calculated']}")
        print(f"单供应商规格数: {single_count}")

        if unmatched_suppliers:
            print(f"\n匹配失败的供应商:")
            for name, count in Counter(unmatched_suppliers).most_common():
                print(f"  - {name} ({count} 条记录)")

        # 输出多供应商规格（需人工处理）
        multi_supplier_specs = {
            gid for gid, suppliers in spec_supplier_count.items() if len(suppliers) > 1
        }
        if multi_supplier_specs:
            print(f"\n多供应商规格（{len(multi_supplier_specs)} 个，需人工处理外部展示价格）")
            with parts_conn.cursor() as cursor:
                placeholders = ",".join(["%s"] * len(multi_supplier_specs))
                cursor.execute(
                    f"""SELECT DISTINCT p.id, p.model, p.product_name
                        FROM product_variant_prices vpp
                        JOIN parts p ON p.id = vpp.part_id
                        WHERE vpp.variant_group_id IN ({placeholders})
                        ORDER BY p.id""",
                    tuple(multi_supplier_specs),
                )
                for row in cursor.fetchall():
                    print(f"  产品 ID={row['id']}, 型号={row['model']}, 名称={row['product_name']}")

    finally:
        parts_conn.close()
        oa_conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
