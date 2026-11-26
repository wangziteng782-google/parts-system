"""数据库连接管理。"""

import os
import queue
import threading
import time

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
    ensure_retail_invoice_columns,
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
    ensure_retail_invoice_columns,
    ensure_sales_query_logs_has_result,
    ensure_part_inquiries_table,
    ensure_inquiry_tables,
    ensure_oa_suppliers_table,
)

_migrated = False

# 每次请求都新建连接时，正式库跨公网建连要 70ms~4s，是接口慢的主因
_POOL_SIZE = max(1, int(os.getenv("PARTS_DB_POOL_SIZE", "10")))
# 空闲超过这个秒数才 ping 一次，避免每个请求都付一次往返
_IDLE_PING_SECONDS = 60


class _ConnectionPool:
    """固定大小的连接池，请求间复用物理连接。"""

    def __init__(self, config, size):
        self._config = config
        self._size = size
        self._free = queue.LifoQueue()
        self._lock = threading.Lock()
        self._created = 0

    def _create(self):
        with self._lock:
            if self._created >= self._size:
                return None
            self._created += 1
        try:
            return pymysql.connect(**self._config)
        except Exception:
            with self._lock:
                self._created -= 1
            raise

    def _drop(self, conn):
        try:
            conn.close()
        except Exception:
            pass
        with self._lock:
            self._created -= 1

    def acquire(self):
        while True:
            try:
                conn, last_used = self._free.get_nowait()
            except queue.Empty:
                conn = self._create()
                if conn is not None:
                    return conn
                # 池满时排队等，不无限建连
                conn, last_used = self._free.get(timeout=30)
            if time.time() - last_used > _IDLE_PING_SECONDS:
                try:
                    conn.ping(reconnect=True)
                except Exception:
                    self._drop(conn)
                    continue
            return conn

    def release(self, conn):
        # 归还前回滚未提交的事务，避免脏事务被下一个请求带走
        try:
            conn.rollback()
        except Exception:
            self._drop(conn)
            return
        self._free.put((conn, time.time()))


class _PooledConnection:
    """把 close() 变成归还连接池，其余方法原样转发。"""

    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    def __getattr__(self, name):
        if self._conn is None:
            raise RuntimeError("连接已归还连接池，不能继续使用")
        return getattr(self._conn, name)

    def close(self):
        conn, self._conn = self._conn, None
        if conn is not None:
            self._pool.release(conn)


_pool = _ConnectionPool(DB_CONFIG, _POOL_SIZE)


def get_db():
    """从连接池取一个主库连接。建表迁移只在进程内第一次调用时执行。"""
    global _migrated
    conn = _PooledConnection(_pool, _pool.acquire())
    if _migrated:
        return conn
    try:
        for ensure in _ENSURE_FUNCS:
            ensure(conn)
    except Exception:
        conn.close()
        raise
    _migrated = True
    return conn
