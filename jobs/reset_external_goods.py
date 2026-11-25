"""清空商品库（sku_code 以 EXT- 开头）的商品及其关联数据，删除前自动备份。

用于外部商品库重新导入前重置数据：
    python -m jobs.reset_external_goods --env test --dry-run   # 只看数量
    python -m jobs.reset_external_goods --env test --yes       # 备份 + 删除
    python -m jobs.reset_external_goods --env prod --yes

备份位置：jobs/backups/ext_backup_{表名}_{时间戳}.csv
不清理 employee_operation_logs，保留操作审计记录。
"""
import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

import pymysql

from jobs._prod_db import describe, prod_config
from parts_system.config.constants import DB_CONFIG

EXT_PARTS = "SELECT id FROM parts WHERE sku_code LIKE 'EXT-%'"

TABLES = [
    ("parts", "SELECT * FROM parts WHERE sku_code LIKE 'EXT-%'"),
    ("product_variant_specs", f"SELECT * FROM product_variant_specs WHERE part_id IN ({EXT_PARTS})"),
    ("product_variant_group_specs", f"SELECT * FROM product_variant_group_specs WHERE part_id IN ({EXT_PARTS})"),
    ("product_variant_prices", f"SELECT * FROM product_variant_prices WHERE part_id IN ({EXT_PARTS})"),
]

BACKUP_TABLES = ("parts", "product_variant_specs", "product_variant_group_specs", "product_variant_prices")

DELETES = [
    ("product_variant_prices", f"DELETE FROM product_variant_prices WHERE part_id IN ({EXT_PARTS})"),
    ("product_variant_group_specs", f"DELETE FROM product_variant_group_specs WHERE part_id IN ({EXT_PARTS})"),
    ("product_variant_specs", f"DELETE FROM product_variant_specs WHERE part_id IN ({EXT_PARTS})"),
    ("duplicate_product_marks", f"DELETE FROM duplicate_product_marks WHERE product_id IN ({EXT_PARTS})"),
    ("part_inquiries", f"DELETE FROM part_inquiries WHERE part_id IN ({EXT_PARTS})"),
    ("sales_product_feedback", f"DELETE FROM sales_product_feedback WHERE parts_id IN ({EXT_PARTS})"),
    ("product_relations", f"DELETE FROM product_relations WHERE product_id IN ({EXT_PARTS})"),
    ("parts", "DELETE FROM parts WHERE sku_code LIKE 'EXT-%'"),
]


def connect(env: str):
    config = dict(prod_config()) if env == "prod" else dict(DB_CONFIG)
    config["charset"] = "utf8mb4"
    config["cursorclass"] = pymysql.cursors.DictCursor
    config.setdefault("connect_timeout", 10)
    return pymysql.connect(**config)


def backup(cur, out_dir: Path, stamp: str) -> int:
    total = 0
    for name, sql in TABLES:
        if name not in BACKUP_TABLES:
            continue
        cur.execute(sql)
        rows = cur.fetchall()
        path = out_dir / f"ext_backup_{name}_{stamp}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as fp:
            if rows:
                writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: ("" if v is None else str(v)) for k, v in row.items()})
        print(f"备份 {name}: {len(rows)} 行 -> {path.name}")
        if name == "parts":
            total = len(rows)
    return total


def main():
    parser = argparse.ArgumentParser(description="清空商品库（EXT-）商品及关联数据")
    parser.add_argument("--env", choices=("test", "prod"), default="test")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不删除")
    parser.add_argument("--yes", action="store_true", help="确认删除")
    args = parser.parse_args()

    print(f"目标库: {describe() if args.env == 'prod' else DB_CONFIG['host'] + '/' + DB_CONFIG['database']}")
    conn = connect(args.env)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM parts WHERE sku_code LIKE 'EXT-%'")
        total = cur.fetchone()["c"]
        print(f"商品库（EXT-）现有 {total} 条")
        if not total:
            print("无需处理")
            return 0
        if args.dry_run:
            for name, sql in TABLES:
                if name == "parts":
                    continue
                cur.execute(sql)
                print(f"  {name}: {len(cur.fetchall())} 行")
            print("dry-run：未删除")
            return 0
        if not args.yes:
            print("需要加 --yes 才会执行删除")
            return 1

        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        out_dir = Path(__file__).resolve().parent / "backups"
        out_dir.mkdir(exist_ok=True)
        backup(cur, out_dir, stamp)

        conn.begin()
        try:
            for name, sql in DELETES:
                cur.execute(sql)
                print(f"删除 {name}: {cur.rowcount} 行")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        print(f"\n商品库已清空（原 {total} 条）")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
