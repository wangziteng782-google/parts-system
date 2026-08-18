"""数据库连接管理。"""

import pymysql

from ..config import DB_CONFIG, OA_DB_CONFIG, logger
from .migration import (
    ensure_product_spec_required_rules,
    ensure_product_variant_tables,
    ensure_technical_params_column,
)


def get_oa_db():
    """获取 OA 数据库连接。"""
    if not OA_DB_CONFIG["password"]:
        raise RuntimeError("未配置 OA_DB_PASSWORD")
    return pymysql.connect(**OA_DB_CONFIG)


def get_db():
    """获取主数据库连接，并执行惰性迁移。"""
    conn = pymysql.connect(**DB_CONFIG)
    ensure_technical_params_column(conn)
    ensure_product_variant_tables(conn)
    ensure_product_spec_required_rules(conn)
    return conn
