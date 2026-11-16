"""数据库连接管理。"""

import pymysql

from ..config import DB_CONFIG, OA_DB_CONFIG, logger
from .migration import (
    ensure_employee_operation_logs_table,
    ensure_inquiry_tables,
    ensure_oa_suppliers_table,
    ensure_part_inquiries_table,
    ensure_parts_indexes,
    ensure_product_spec_required_rules,
    ensure_product_variant_tables,
    ensure_sales_query_logs_has_result,
    ensure_technical_params_column,
)


def get_oa_db():
    """获取 OA 数据库连接。"""
    if not OA_DB_CONFIG["password"]:
        raise RuntimeError("未配置 OA_DB_PASSWORD")
    return pymysql.connect(**OA_DB_CONFIG)


_ENSURE_FUNCS = (
    ensure_employee_operation_logs_table,
    ensure_technical_params_column,
    ensure_parts_indexes,
    ensure_product_variant_tables,
    ensure_product_spec_required_rules,
    ensure_sales_query_logs_has_result,
    ensure_part_inquiries_table,
    ensure_inquiry_tables,
    ensure_oa_suppliers_table,
)

_migrated = False


def get_db():
    """获取主数据库连接。建表迁移只在进程内第一次调用时执行，之后每次请求不再重复检查。"""
    global _migrated
    conn = pymysql.connect(**DB_CONFIG)
    if _migrated:
        return conn
    for ensure in _ENSURE_FUNCS:
        ensure(conn)
    _migrated = True
    return conn
