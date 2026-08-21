"""回填 display_price_min/max：对所有有规格的产品调用已有计算逻辑。

用法：
    python jobs/backfill_display_price.py
"""
import logging
import sys
import os

import pymysql
import pymysql.cursors

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parts_system.routes.variants import _recalculate_part_display_price

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_display_price")


def db_config() -> dict:
    """Parts 系统正式库连接"""
    return {
        "host": os.getenv("PARTS_DB_HOST", "120.46.152.222"),
        "port": int(os.getenv("PARTS_DB_PORT", "3306")),
        "user": os.getenv("PARTS_DB_USER", "parts_database"),
        "password": os.getenv("PARTS_DB_PASSWORD", "1234"),
        "database": os.getenv("PARTS_DB_NAME", "parts_database"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }


def main():
    conn = pymysql.connect(**db_config())
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT part_id FROM product_variant_prices")
        part_ids = [row["part_id"] for row in cur.fetchall()]
        total = len(part_ids)
        log.info("共 %d 个产品需要回填 display_price_min/max", total)

        success = 0
        for i, part_id in enumerate(part_ids, 1):
            try:
                _recalculate_part_display_price(part_id, cur)
                success += 1
                if i % 100 == 0 or i == total:
                    log.info("进度: %d/%d", i, total)
            except Exception as exc:
                log.error("回填失败 part_id=%s: %s", part_id, exc)
                conn.rollback()

        conn.commit()
        log.info("完成: 成功 %d/%d", success, total)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
