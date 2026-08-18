"""数据库包：连接管理与迁移。"""

from .database import get_db, get_oa_db
from .migration import (
    ensure_duplicate_marks_table,
    ensure_employee_operation_logs_table,
    ensure_product_spec_required_rules,
    ensure_product_variant_tables,
    ensure_technical_params_column,
)

__all__ = [
    "get_db", "get_oa_db",
    "ensure_duplicate_marks_table",
    "ensure_employee_operation_logs_table",
    "ensure_product_spec_required_rules",
    "ensure_product_variant_tables",
    "ensure_technical_params_column",
]
