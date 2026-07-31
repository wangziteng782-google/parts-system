"""Import the online yh_admin_user snapshot into parts_database.

Only run this job when refreshing the local user lookup table. Existing data is
protected by default; pass --replace to explicitly replace a populated table.
"""

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pymysql

from parts_system.shared import DB_CONFIG


DEFAULT_SOURCE = Path(r"C:\Users\yiti\Desktop\yh_admin_user.sql")


def table_exists(cursor):
    cursor.execute("SHOW TABLES LIKE 'yh_admin_user'")
    return cursor.fetchone() is not None


def table_count(cursor):
    cursor.execute("SELECT COUNT(*) AS count FROM yh_admin_user")
    return cursor.fetchone()["count"]


def split_statements(sql_text):
    # The Navicat export contains simple SET/DDL and one INSERT per line; none
    # of its quoted values contains a semicolon.
    return [statement.strip() for statement in sql_text.split(";") if statement.strip()]


def main():
    parser = argparse.ArgumentParser(description="导入 yh_admin_user 用户表快照")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="明确允许替换已经存在且有数据的 yh_admin_user 表",
    )
    args = parser.parse_args()

    if not args.source.exists():
        raise SystemExit(f"SQL 文件不存在：{args.source}")

    sql_text = args.source.read_text(encoding="utf-8-sig")
    statements = split_statements(sql_text)
    if not any("CREATE TABLE `yh_admin_user`" in item for item in statements):
        raise SystemExit("SQL 文件中没有找到 yh_admin_user 建表语句")

    conn = pymysql.connect(**DB_CONFIG)
    try:
        cursor = conn.cursor()
        if table_exists(cursor):
            count = table_count(cursor)
            if count and not args.replace:
                raise SystemExit(
                    f"yh_admin_user 已有 {count} 条数据；如确认替换，请使用 --replace"
                )

        try:
            for statement in statements:
                cursor.execute(statement)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        count = table_count(cursor)
        cursor.execute(
            """
            SELECT id, username, nickname
            FROM yh_admin_user
            ORDER BY id
            LIMIT 3
            """
        )
        preview = cursor.fetchall()
        print(f"导入完成：yh_admin_user 共 {count} 条用户数据")
        for row in preview:
            print(
                f"  id={row['id']} | username={row['username']} | "
                f"nickname={row['nickname']}"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
