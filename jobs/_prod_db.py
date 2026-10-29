"""脚本用数据库连接：优先读 jobs/.env.prod，没有就用项目 .env 里的配置。

线上 parts 库在服务器本机 127.0.0.1，本地要连必须走 SSH 隧道，
所以本地用 PROD_DB_* 指向隧道端口，服务器上直接跑则退回项目 .env。
"""

import os

import pymysql
from dotenv import load_dotenv

from parts_system.config.constants import DB_CONFIG, OA_DB_CONFIG, PROJECT_ROOT

# 只补 PROD_DB_* 这几个键，不影响项目 .env 的其它配置
load_dotenv(PROJECT_ROOT / "jobs" / ".env.prod", override=False)


def prod_config():
    """正式 products 库的连接参数。"""
    host = os.getenv("PROD_DB_HOST", "").strip()
    if not host:
        return dict(DB_CONFIG)
    return {
        "host": host,
        "port": int(os.getenv("PROD_DB_PORT", "3306")),
        "user": os.getenv("PROD_DB_USER", "").strip(),
        "password": os.getenv("PROD_DB_PASSWORD", ""),
        "database": os.getenv("PROD_DB_NAME", "parts_database").strip(),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": int(os.getenv("PROD_DB_CONNECT_TIMEOUT", "10")),
    }


def prod_conn():
    """正式 products 库连接。"""
    return pymysql.connect(**prod_config())


def oa_conn():
    """OA 库连接，沿用项目 .env 里的 OA_DB_*。"""
    return pymysql.connect(**OA_DB_CONFIG)


def describe():
    """打印当前连的是哪个库，避免又连到本地副本。"""
    config = prod_config()
    return "%s@%s:%s/%s" % (config["user"], config["host"], config["port"], config["database"])
