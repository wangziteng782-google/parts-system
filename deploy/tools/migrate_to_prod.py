"""把测试库的询价落地表复制到正式库：先建表，再搬数据。

用法：
    python deploy/tools/migrate_to_prod.py                # 建表 + 导数据
    python deploy/tools/migrate_to_prod.py --only-create  # 只建表
    python deploy/tools/migrate_to_prod.py --only-data    # 只导数据
    python deploy/tools/migrate_to_prod.py --truncate     # 导之前先清空目标表

源库取项目 .env 里配的 DB_CONFIG（当前测试库）。
正式库填下面的 TARGET_DB，或者用 PROD_DB_HOST / PROD_DB_PORT / PROD_DB_USER /
PROD_DB_PASSWORD / PROD_DB_NAME 这几个环境变量覆盖。
"""
import argparse
import os
import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from parts_system.config import DB_CONFIG  # noqa: E402
from parts_system.model.migration import ensure_inquiry_tables  # noqa: E402

# ===== 正式库连接信息，填这里 =====
TARGET_DB = {
    "host": os.getenv("PROD_DB_HOST", ""),
    "port": int(os.getenv("PROD_DB_PORT", "3306")),
    "user": os.getenv("PROD_DB_USER", ""),
    "password": os.getenv("PROD_DB_PASSWORD", ""),
    "database": os.getenv("PROD_DB_NAME", "parts_database"),
    "charset": "utf8mb4",
}

# 要搬的表，按依赖顺序。要带 parts / part_inquiries 就加到前面
TABLES = [
    "inquiry_records",
    "inquiry_quotes",
    "inquiry_communications",
]

BATCH = 1000


def connect_target():
    missing = [k for k in ("host", "user", "password") if not TARGET_DB[k]]
    if missing:
        raise SystemExit(
            "正式库连接信息没填全：" + "、".join(missing)
            + "\n改 deploy/tools/migrate_to_prod.py 里的 TARGET_DB，或设置 PROD_DB_* 环境变量"
        )
    return pymysql.connect(**TARGET_DB)


def primary_keys(cursor, table):
    cursor.execute(f"SHOW KEYS FROM `{table}` WHERE Key_name='PRIMARY'")
    return [row[4] for row in cursor.fetchall()]


def copy_table(src, dst, table, truncate=False):
    # 项目默认 cursor 是 DictCursor，这里要按位置取值，换成普通 cursor
    s = src.cursor(pymysql.cursors.Cursor)
    s.execute(f"SELECT * FROM `{table}`")
    columns = [d[0] for d in s.description]
    rows = s.fetchall()
    if not rows:
        print(f"  {table}: 源表为空，跳过")
        return 0

    d = dst.cursor(pymysql.cursors.Cursor)
    if truncate:
        d.execute(f"DELETE FROM `{table}`")
        dst.commit()

    pk = set(primary_keys(d, table))
    col_sql = ", ".join(f"`{c}`" for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    updates = [f"`{c}`=VALUES(`{c}`)" for c in columns if c not in pk]
    if updates:
        sql = (f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders}) "
               f"ON DUPLICATE KEY UPDATE {', '.join(updates)}")
    else:
        sql = f"REPLACE INTO `{table}` ({col_sql}) VALUES ({placeholders})"

    # 逐条 execute：pymysql 的 executemany 对这种带 VALUES() 的语句会解析出错
    for index, row in enumerate(rows, start=1):
        d.execute(sql, row)
        if index % BATCH == 0:
            dst.commit()
            print(f"    {index}/{len(rows)}")
    dst.commit()
    print(f"  {table}: 写入 {len(rows)} 行")
    return len(rows)


def verify(src, dst, tables):
    print("\n行数核对：")
    ok = True
    for table in tables:
        s = src.cursor(pymysql.cursors.Cursor)
        s.execute(f"SELECT COUNT(*) FROM `{table}`")
        src_count = s.fetchone()[0]
        d = dst.cursor(pymysql.cursors.Cursor)
        d.execute(f"SELECT COUNT(*) FROM `{table}`")
        dst_count = d.fetchone()[0]
        flag = "OK" if src_count == dst_count else "不一致"
        if src_count != dst_count:
            ok = False
        print(f"  {table:<26} 源 {src_count:>7}  目标 {dst_count:>7}  {flag}")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-create", action="store_true", help="只建表")
    parser.add_argument("--only-data", action="store_true", help="只导数据")
    parser.add_argument("--truncate", action="store_true", help="导之前清空目标表")
    args = parser.parse_args()

    src_cfg = dict(DB_CONFIG)
    print(f"源库   {src_cfg.get('host')}:{src_cfg.get('port', 3306)}/{src_cfg.get('database')}")
    print(f"目标库 {TARGET_DB['host']}:{TARGET_DB['port']}/{TARGET_DB['database']}")

    src = pymysql.connect(**src_cfg)
    dst = connect_target()
    try:
        if not args.only_data:
            print("\n[1/2] 建表")
            ensure_inquiry_tables(dst)
            print("  三张表已就绪")

        if not args.only_create:
            print("\n[2/2] 导数据")
            for table in TABLES:
                copy_table(src, dst, table, truncate=args.truncate)
            verify(src, dst, TABLES)
    finally:
        src.close()
        dst.close()

    print("\n完成")


if __name__ == "__main__":
    main()
