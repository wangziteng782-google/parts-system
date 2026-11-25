"""把商品库（EXT-）里「规格型号」但规格值为空的记录改成「规格 / 默认」。

背景：型号和名称都没参与拆分的商品，导入时规格值落成空串，
商品详情和销售页的规格卡片上就是一个空标签，看着像坏了。

用法：
    python -m jobs.fix_ext_empty_spec --env test          # 只看数量
    python -m jobs.fix_ext_empty_spec --env test --yes    # 备份 + 更新
    python -m jobs.fix_ext_empty_spec --env prod --yes
"""
import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

from jobs._prod_db import describe, prod_config
from jobs.import_external_goods import DEFAULT_SPEC_NAME, DEFAULT_SPEC_VALUE, SPEC_NAME
from parts_system.config.constants import DB_CONFIG

# LEFT(sku_code,4) 代替 LIKE，避免 % 被 pymysql 当占位符
SELECT_SQL = """
SELECT s.id, s.part_id, p.sku_code, p.product_name, s.spec_name, s.spec_value
  FROM product_variant_specs s
  JOIN parts p ON p.id = s.part_id
 WHERE LEFT(p.sku_code, 4) = 'EXT-'
   AND s.spec_name = %s
   AND (s.spec_value IS NULL OR TRIM(s.spec_value) = '')
 ORDER BY s.id
"""

UPDATE_SQL = """
UPDATE product_variant_specs s
  JOIN parts p ON p.id = s.part_id
   SET s.spec_name = %s, s.spec_value = %s
 WHERE LEFT(p.sku_code, 4) = 'EXT-'
   AND s.spec_name = %s
   AND (s.spec_value IS NULL OR TRIM(s.spec_value) = '')
"""


def connect(env: str):
    config = dict(prod_config()) if env == "prod" else dict(DB_CONFIG)
    config["charset"] = "utf8mb4"
    config["cursorclass"] = pymysql.cursors.DictCursor
    config.setdefault("connect_timeout", 10)
    return pymysql.connect(**config)


def backup(rows):
    folder = Path(__file__).resolve().parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"ext_empty_spec_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["spec_id", "part_id", "sku_code", "product_name", "spec_name", "spec_value"])
        for row in rows:
            writer.writerow([row["id"], row["part_id"], row["sku_code"],
                             row["product_name"], row["spec_name"], row["spec_value"]])
    return path


def main():
    parser = argparse.ArgumentParser(description="空规格值改成默认规格")
    parser.add_argument("--env", choices=("test", "prod"), default="test")
    parser.add_argument("--yes", action="store_true", help="确认写入")
    args = parser.parse_args()

    print(f"目标库: {describe() if args.env == 'prod' else DB_CONFIG['host'] + '/' + DB_CONFIG['database']}")
    conn = connect(args.env)
    try:
        cur = conn.cursor()
        cur.execute(SELECT_SQL, (SPEC_NAME,))
        rows = cur.fetchall()
        print(f"规格名「{SPEC_NAME}」且值为空的记录: {len(rows)} 条")
        for row in rows[:5]:
            print(f"  样例: spec_id={row['id']} {row['sku_code']} {row['product_name']}")

        if not args.yes:
            print(f"\n确认后加 --yes 执行，会改成「{DEFAULT_SPEC_NAME} / {DEFAULT_SPEC_VALUE}」")
            return 0
        if not rows:
            print("没有需要修的数据")
            return 0

        path = backup(rows)
        cur.execute(UPDATE_SQL, (DEFAULT_SPEC_NAME, DEFAULT_SPEC_VALUE, SPEC_NAME))
        conn.commit()
        print(f"已更新 {cur.rowcount} 条，备份: {path}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
