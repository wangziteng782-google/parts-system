"""钢丝绳（EXT 商品）鼎恒鑫报价：把含普票价格并入含专票。

鼎恒鑫报的钢丝绳价格实际都是含专票价，原来错填在「含普票」列。
只移动价格 > 0 的行，价格为 0 或空的保持原样。

用法：
    python -m jobs.move_wire_prices_to_special --env prod --dry-run
    python -m jobs.move_wire_prices_to_special --env prod
"""
import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymysql

from parts_system.config.constants import DB_CONFIG
from parts_system.inquiry_sync import PROD_DB

NAME_KEYWORD = "%钢丝绳%"
SUPPLIER_KEYWORD = "%鼎恒鑫%"

SELECT_SQL = """
SELECT v.id, v.part_id, p.sku_code, p.product_name, p.model, v.variant_group_id,
       v.supplier, v.no_tax_price, v.purchase_special_invoice, v.purchase_general_invoice
  FROM product_variant_prices v JOIN parts p ON p.id = v.part_id
 WHERE p.sku_code LIKE 'EXT-%%'
   AND p.product_name LIKE %s
   AND v.supplier LIKE %s
   AND COALESCE(v.purchase_general_invoice, 0) > 0
   AND COALESCE(v.purchase_special_invoice, 0) = 0
 ORDER BY v.part_id, v.id
"""

UPDATE_SQL = """
UPDATE product_variant_prices
   SET purchase_special_invoice = purchase_general_invoice,
       purchase_general_invoice = NULL
 WHERE id = %s
"""


def connect(env):
    cfg = dict(PROD_DB if env == "prod" else DB_CONFIG)
    cfg["charset"] = "utf8mb4"
    cfg["cursorclass"] = pymysql.cursors.DictCursor
    cfg["connect_timeout"] = 25
    return pymysql.connect(**cfg)


def main():
    parser = argparse.ArgumentParser(description="钢丝绳鼎恒鑫含普票价并入含专票")
    parser.add_argument("--env", choices=("test", "prod"), default="test")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = connect(args.env)
    cur = conn.cursor()
    cur.execute(SELECT_SQL, (NAME_KEYWORD, SUPPLIER_KEYWORD))
    rows = cur.fetchall()

    print(f"目标库 {conn.get_host_info()} / {args.env}")
    print(f"待移动行: {len(rows)} 行，涉及商品 {len({r['part_id'] for r in rows})} 个")

    if not rows:
        conn.close()
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / "tmp" / f"backup_wire_prices_{args.env}_{stamp}.csv"
    backup.parent.mkdir(exist_ok=True)
    with backup.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"已备份旧值 -> {backup}")

    if args.dry_run:
        for row in rows[:10]:
            print(
                f"   #{row['id']} {row['sku_code']} {row['model']} "
                f"普票 {row['purchase_general_invoice']} -> 专票"
            )
        print("[dry-run] 未写入")
        conn.close()
        return 0

    ok = fail = 0
    for row in rows:
        try:
            cur.execute(UPDATE_SQL, (row["id"],))
            conn.commit()
            ok += 1
        except Exception as exc:
            conn.rollback()
            fail += 1
            print(f"   #{row['id']} 失败: {type(exc).__name__}: {exc}")

    print(f"\n完成：成功 {ok}，失败 {fail}")
    conn.close()
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
