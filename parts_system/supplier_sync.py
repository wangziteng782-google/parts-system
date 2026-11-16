"""从 OA 拉取供应商名称与开票能力，覆盖写入测试库和正式库。

用法：
    python -m parts_system.supplier_sync

连接信息写死在文件顶部，不读 .env。每次全量覆盖 oa_suppliers：
OA 里软删的供应商，本地跟着消失；改名或改税点，本地跟着变。
"""
import logging
import sys
import time

import pymysql

BATCH = 500
RETRIES = 3

# ============ 连接信息（写死，改这里就行） ============
OA_DB = {
    "host": "120.46.152.222",
    "port": 3306,
    "user": "oa_yixiuti",
    "password": "npFKTmTpzTzGAEcr",
    "database": "oa_yixiuti",
    "charset": "utf8mb4",
    "connect_timeout": 10,
    "read_timeout": 120,
}

TEST_DB = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "1234",
    "database": "parts_database",
    "charset": "utf8mb4",
    "connect_timeout": 10,
}

PROD_DB = {
    "host": "120.46.152.222",
    "port": 3306,
    "user": "parts_database",
    "password": "1234",
    "database": "parts_database",
    "charset": "utf8mb4",
    "connect_timeout": 10,
}

ENVS = (("测试", TEST_DB), ("正式", PROD_DB))

# 口径与 /api/oa/suppliers/{id} 完全一致：开票能力取 MAX，税点去重拼接
SUPPLIER_SQL = """
SELECT s.id AS oa_supplier_id, s.supplier_name,
       MAX(d.is_special_invoice) AS is_special_invoice,
       MAX(d.is_normal_invoice) AS is_normal_invoice,
       MAX(d.is_no_invoice) AS is_no_invoice,
       GROUP_CONCAT(DISTINCT CASE WHEN d.special_tax_point > '' THEN d.special_tax_point END) AS special_tax_point,
       GROUP_CONCAT(DISTINCT CASE WHEN d.normal_tax_point > '' THEN d.normal_tax_point END) AS normal_tax_point,
       GROUP_CONCAT(DISTINCT CASE WHEN d.no_tax_point > '' THEN d.no_tax_point END) AS no_tax_point
  FROM yh_supplier s
  LEFT JOIN yh_supplier_detail d ON s.id = d.supplier_id AND d.delete_time IS NULL
 WHERE s.delete_time IS NULL
 GROUP BY s.id, s.supplier_name
 ORDER BY s.id
"""

DELETE_SQL = "DELETE FROM oa_suppliers"

UPSERT_SQL = """
INSERT INTO oa_suppliers (oa_supplier_id, supplier_name, is_special_invoice,
    is_normal_invoice, is_no_invoice, special_tax_point, normal_tax_point, no_tax_point)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
ON DUPLICATE KEY UPDATE supplier_name=VALUES(supplier_name),
    is_special_invoice=VALUES(is_special_invoice),
    is_normal_invoice=VALUES(is_normal_invoice),
    is_no_invoice=VALUES(is_no_invoice),
    special_tax_point=VALUES(special_tax_point),
    normal_tax_point=VALUES(normal_tax_point),
    no_tax_point=VALUES(no_tax_point)
"""

log = logging.getLogger("supplier_sync")


def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    log.handlers.clear()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def describe(config):
    return f"{config['host']}:{config['port']}/{config['database']}"


def configured(config):
    return bool(config.get("host") and config.get("user"))


def connect(config):
    return pymysql.connect(**config, cursorclass=pymysql.cursors.DictCursor)


def fetch_suppliers():
    """读 OA，失败重试 RETRIES 次。"""
    for attempt in range(1, RETRIES + 1):
        conn = None
        started = time.perf_counter()
        try:
            conn = connect(OA_DB)
            cur = conn.cursor()
            cur.execute(SUPPLIER_SQL)
            rows = cur.fetchall()
            log.info(f"[OA] 供应商 {len(rows):,} 条  {time.perf_counter() - started:.1f}s")
            return rows
        except Exception as exc:
            if attempt == RETRIES:
                log.error(f"[OA] 供应商读取连续 {RETRIES} 次失败：{type(exc).__name__}: {exc}")
                raise
            log.warning(f"[OA] 供应商读取第 {attempt} 次失败（{type(exc).__name__}），3 秒后重试")
            time.sleep(3)
        finally:
            if conn:
                conn.close()


def build_rows(suppliers):
    return [
        (r["oa_supplier_id"], r["supplier_name"],
         int(bool(r["is_special_invoice"])), int(bool(r["is_normal_invoice"])),
         int(bool(r["is_no_invoice"])),
         r["special_tax_point"], r["normal_tax_point"], r["no_tax_point"])
        for r in suppliers
    ]


def write_env(name, config, rows):
    """全量覆盖一个环境，返回 True/False。失败只影响这个环境。"""
    try:
        conn = connect(config)
    except Exception as exc:
        log.error(f"[{name}] 连接 {describe(config)} 失败：{type(exc).__name__}: {exc}")
        return False
    log.info(f"[{name}] 写入 {describe(config)}")
    try:
        started = time.perf_counter()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM oa_suppliers")
        before = list(cur.fetchone().values())[0]
        # 先清空再写，删和插在同一个事务里，中途失败回滚，表不会空着
        cur.execute(DELETE_SQL)
        for i in range(0, len(rows), BATCH):
            cur.executemany(UPSERT_SQL, rows[i:i + BATCH])
        conn.commit()
        cur.execute("SELECT COUNT(*) AS n FROM oa_suppliers")
        after = list(cur.fetchone().values())[0]
        log.info(
            f"[{name}]   oa_suppliers  覆盖 {len(rows):,} 行"
            f"  库内 {before:,} -> {after:,}  {time.perf_counter() - started:.1f}s"
        )
        return True
    except Exception as exc:
        conn.rollback()
        log.error(f"[{name}] 写入失败：{type(exc).__name__}: {exc}")
        return False
    finally:
        conn.close()


def main():
    setup_logging()
    log.info("=" * 66)
    log.info("OA 供应商同步开始")
    log.info(f"[OA]   {describe(OA_DB)}")
    for name, config in ENVS:
        log.info(f"[{name}] {describe(config) if configured(config) else '未配置，跳过'}")
    log.info("=" * 66)
    started = time.perf_counter()

    rows = build_rows(fetch_suppliers())

    results = []
    written = {}
    for name, config in ENVS:
        if not configured(config):
            log.warning(f"[{name}] 跳过：{name}库的 host/user 还没填")
            results.append((name, None))
            continue
        target = describe(config)
        if target in written:
            log.warning(f"[{name}] 跳过：和「{written[target]}」是同一个库（{target}）")
            results.append((name, None))
            continue
        written[target] = name
        results.append((name, write_env(name, config, rows)))

    total = time.perf_counter() - started
    done = [name for name, ok in results if ok]
    skipped = [name for name, ok in results if ok is None]
    failed = [name for name, ok in results if ok is False]

    log.info("-" * 66)
    log.info(f"写入成功 {len(done)} 个：{'、'.join(done) if done else '无'}")
    if skipped:
        log.warning(f"跳过 {len(skipped)} 个：{'、'.join(skipped)}（未配置，或与前面的环境是同一个库）")
    if failed:
        log.error(f"失败 {len(failed)} 个：{'、'.join(failed)}")
    log.info(f"总用时 {total:.1f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
