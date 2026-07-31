#!/usr/bin/env python
"""导出SKU、规格、供应商和价格的完整联表报表。"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate_parts_to_spu import target_db_config


PROJECT_DIR = Path(__file__).resolve().parents[1]
SQL_PATH = PROJECT_DIR / "docs" / "sku_supplier_price_query.sql"
OUTPUT_PATH = PROJECT_DIR / "jobs" / "sku_supplier_price_report.csv"


def main() -> int:
    sql = SQL_PATH.read_text(encoding="utf-8")
    conn = pymysql.connect(**target_db_config())
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            fieldnames = [item[0] for item in cursor.description]
    finally:
        conn.close()

    with OUTPUT_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"已导出{len(rows)}行：{OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
