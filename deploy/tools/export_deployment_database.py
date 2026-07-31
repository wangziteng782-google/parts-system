"""Export parts_database for a safe one-time test-server import.

The dump uses a temporary MySQL client config so the password is not placed on
the command line. MySQL 8/9-only collations are normalized for MySQL 5.7+
compatibility, and a manifest is generated for post-import verification.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from parts_system.shared import DB_CONFIG, get_db


DEFAULT_MYSQLDUMP = Path(
    r"C:\Program Files\MySQL\MySQL Server 9.7\bin\mysqldump.exe"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "deploy" / "artifacts" / "parts_database.sql"
)


def normalize_for_mysql57(sql_text):
    sql_text = re.sub(
        r"utf8mb4_0900_[a-z0-9_]+",
        "utf8mb4_unicode_ci",
        sql_text,
        flags=re.IGNORECASE,
    )
    sql_text = sql_text.replace("utf8mb3_general_ci", "utf8_general_ci")
    sql_text = re.sub(r"\butf8mb3\b", "utf8", sql_text, flags=re.IGNORECASE)
    return sql_text


def database_manifest():
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema=DATABASE()
            ORDER BY table_name
            """
        )
        tables = [row["TABLE_NAME"] for row in cursor.fetchall()]
        counts = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) AS count FROM `{table}`")
            counts[table] = cursor.fetchone()["count"]
        return {"database": DB_CONFIG["database"], "tables": counts}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="导出宝塔测试部署数据库")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mysqldump", type=Path, default=DEFAULT_MYSQLDUMP)
    parser.add_argument(
        "--keep-mysql8-collation",
        action="store_true",
        help="目标明确为MySQL 8+时保留0900字符集",
    )
    args = parser.parse_args()

    if not args.mysqldump.exists():
        raise SystemExit(f"找不到 mysqldump：{args.mysqldump}")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(".sql.tmp")

    config_text = (
        "[client]\n"
        f"host={DB_CONFIG['host']}\n"
        f"port={DB_CONFIG['port']}\n"
        f"user={DB_CONFIG['user']}\n"
        f"password={DB_CONFIG['password']}\n"
        f"default-character-set={DB_CONFIG['charset']}\n"
    )

    config_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".cnf",
            delete=False,
        ) as config_file:
            config_file.write(config_text)
            config_path = Path(config_file.name)

        command = [
            str(args.mysqldump),
            f"--defaults-extra-file={config_path}",
            "--single-transaction",
            "--skip-add-locks",
            "--routines",
            "--triggers",
            "--hex-blob",
            "--set-gtid-purged=OFF",
            "--default-character-set=utf8mb4",
            "--skip-comments",
            f"--result-file={temporary_output}",
            DB_CONFIG["database"],
        ]
        subprocess.run(command, check=True)

        sql_text = temporary_output.read_text(encoding="utf-8")
        if not args.keep_mysql8_collation:
            sql_text = normalize_for_mysql57(sql_text)
        output.write_text(sql_text, encoding="utf-8", newline="\n")
        temporary_output.unlink(missing_ok=True)

        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        manifest = database_manifest()
        manifest.update(
            {
                "dump_file": output.name,
                "size_bytes": output.stat().st_size,
                "sha256": digest,
                "mysql57_compatible_collation": not args.keep_mysql8_collation,
            }
        )
        manifest_path = output.with_suffix(".manifest.json")
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"数据库导出完成：{output}")
        print(f"校验清单：{manifest_path}")
        print(f"文件大小：{output.stat().st_size / 1024 / 1024:.2f} MB")
        print(f"SHA256：{digest}")
    finally:
        if config_path and config_path.exists():
            try:
                os.remove(config_path)
            except OSError:
                pass
        temporary_output.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
