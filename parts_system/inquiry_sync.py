"""把 OA 的询价任务、明细报价、沟通记录同步到测试库和正式库。

用法：
    python -m parts_system.inquiry_sync

OA 只读一遍，再依次写测试库、正式库。三张表全部 ON DUPLICATE KEY UPDATE，可重复执行。
连接信息写死在文件顶部，不读 .env。某个环境连不上不影响另一个，最后按失败数返回退出码。
"""
import logging
import sys
import time
from collections import defaultdict

import pymysql

from .routes.inquiry_match import _pick_purchase_price

BATCH = 500
RETRIES = 3
TABLES = ("inquiry_quotes", "inquiry_records", "inquiry_communications")

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

# 正式库：host / user / password 填上就会一起写，留空则只跑测试库
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

MISSION_SQL = """
SELECT m.id AS inquiry_mission_id, m.order_goods_id, m.mission_sn, m.mission_type, m.used_time,
       COALESCE(NULLIF(TRIM(a.nickname), ''), a.username) AS create_user,
       g.goods_name, g.ele_type AS model, g.goods_spec, g.images, g.goods_num, g.invoice,
       g.inquiry_time, g.goods_describe,
       m.quotation_type, m.purchase_price, m.post_fee_purchase, m.post_fee_has_tax_purchase,
       g.quotation_type AS goods_quotation_type, g.jh_goods_price, g.jh_goods_price_has_tax,
       s.supplier_name AS goods_supplier_name,
       f.factory_name,
       COALESCE(m.renew_time, m.update_time, m.finish_time, m.create_time, g.quote_time,
                g.update_time, g.inquiry_time, g.create_time) AS quote_updated_at,
       m.create_time
  FROM yh_query_goods_mission m
  LEFT JOIN yh_admin_user a ON a.id=m.admin_id
  LEFT JOIN yh_query_order_goods g ON g.id=m.order_goods_id
  LEFT JOIN yh_factory f ON f.id=g.factory AND f.delete_time IS NULL
  LEFT JOIN yh_supplier s ON s.id=g.supplier AND s.delete_time IS NULL
 WHERE m.mission_type IN (1,3) AND m.mission_status=4 AND m.delete_time IS NULL
"""

QUOTE_SQL = """
SELECT d.id, d.mission_id, d.supplier_name, d.purchase_source, d.goods_spec, d.warehouse,
       d.reminder, d.purchase_quotation_type, d.jh_goods_price, d.jh_goods_price_has_tax,
       d.profit_rate, d.jh_post_fee, d.purchase_price, d.is_selected,
       f.factory_name, b.brand_name AS ele_brand_name
  FROM yh_query_goods_mission_detail d
  LEFT JOIN yh_factory f ON f.id=d.factory AND f.delete_time IS NULL
  LEFT JOIN yh_ele_brand b ON b.id=d.ele_brand AND b.delete_time IS NULL
 WHERE d.delete_time IS NULL
 ORDER BY d.mission_id, d.is_selected DESC, d.id DESC
"""

CHAT_SQL = """
SELECT qa.id, qa.order_goods_id, qa.content, qa.attachments,
       COALESCE(NULLIF(TRIM(u.nickname), ''), u.username) AS creator, qa.create_time
  FROM yh_query_goods_qa qa
  LEFT JOIN yh_admin_user u ON u.id=qa.admin_id
 WHERE qa.delete_time IS NULL
"""

QUOTE_UPSERT = """
INSERT INTO inquiry_quotes (id, mission_id, supplier_name, purchase_source, factory_name,
    ele_brand_name, goods_spec, warehouse, reminder, purchase_quotation_type, jh_goods_price,
    jh_goods_price_has_tax, profit_rate, jh_post_fee, purchase_price, is_selected)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON DUPLICATE KEY UPDATE mission_id=VALUES(mission_id), supplier_name=VALUES(supplier_name),
    purchase_source=VALUES(purchase_source), factory_name=VALUES(factory_name),
    ele_brand_name=VALUES(ele_brand_name), goods_spec=VALUES(goods_spec),
    warehouse=VALUES(warehouse), reminder=VALUES(reminder),
    purchase_quotation_type=VALUES(purchase_quotation_type),
    jh_goods_price=VALUES(jh_goods_price), jh_goods_price_has_tax=VALUES(jh_goods_price_has_tax),
    profit_rate=VALUES(profit_rate), jh_post_fee=VALUES(jh_post_fee),
    purchase_price=VALUES(purchase_price), is_selected=VALUES(is_selected)
"""

RECORD_UPSERT = """
INSERT INTO inquiry_records (inquiry_mission_id, order_goods_id, mission_sn, mission_type,
    used_time, product_name, model, specification, product_brand, images, goods_num, invoice,
    inquiry_time, goods_describe, purchase_price, quotation_type, post_fee_purchase,
    post_fee_has_tax_purchase, price_label, quote_updated_at, create_user, create_time)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON DUPLICATE KEY UPDATE order_goods_id=VALUES(order_goods_id), mission_sn=VALUES(mission_sn),
    mission_type=VALUES(mission_type), used_time=VALUES(used_time),
    product_name=VALUES(product_name), model=VALUES(model), specification=VALUES(specification),
    product_brand=VALUES(product_brand), images=VALUES(images), goods_num=VALUES(goods_num),
    invoice=VALUES(invoice), inquiry_time=VALUES(inquiry_time),
    goods_describe=VALUES(goods_describe), purchase_price=VALUES(purchase_price),
    quotation_type=VALUES(quotation_type), post_fee_purchase=VALUES(post_fee_purchase),
    post_fee_has_tax_purchase=VALUES(post_fee_has_tax_purchase),
    price_label=VALUES(price_label), quote_updated_at=VALUES(quote_updated_at),
    create_user=VALUES(create_user), create_time=VALUES(create_time)
"""

CHAT_UPSERT = """
INSERT INTO inquiry_communications (id, order_goods_id, content, attachments, creator, create_time)
VALUES (%s,%s,%s,%s,%s,%s)
ON DUPLICATE KEY UPDATE order_goods_id=VALUES(order_goods_id), content=VALUES(content),
    attachments=VALUES(attachments), creator=VALUES(creator), create_time=VALUES(create_time)
"""

log = logging.getLogger("inquiry_sync")


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


def oa_query(label, sql, params=()):
    """读 OA，失败重试 RETRIES 次。"""
    for attempt in range(1, RETRIES + 1):
        conn = None
        started = time.perf_counter()
        try:
            conn = connect(OA_DB)
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            log.info(f"[OA] {label} {len(rows):,} 条  {time.perf_counter() - started:.1f}s")
            return rows
        except Exception as exc:
            if attempt == RETRIES:
                log.error(f"[OA] {label} 连续 {RETRIES} 次失败：{type(exc).__name__}: {exc}")
                raise
            log.warning(f"[OA] {label} 第 {attempt} 次失败（{type(exc).__name__}），3 秒后重试")
            time.sleep(3)
        finally:
            if conn:
                conn.close()


def build_payload(missions, quotes, chats):
    """把 OA 原始行拼成三张表的写入参数，返回 (payload, 主行补齐数)。"""
    quotes_by_mission = defaultdict(list)
    for q in quotes:
        quotes_by_mission[int(q["mission_id"])].append(q)

    quote_rows = [
        (q["id"], q["mission_id"], q["supplier_name"], q["purchase_source"], q["factory_name"],
         q["ele_brand_name"], q["goods_spec"], q["warehouse"], q["reminder"],
         q["purchase_quotation_type"], q["jh_goods_price"], q["jh_goods_price_has_tax"],
         q["profit_rate"], q["jh_post_fee"], q["purchase_price"], q["is_selected"])
        for q in quotes
    ]
    # 没有明细报价的询价，用商品主行的供应商和价格补一条，主键取 -mission_id
    for m in missions:
        mission_id = int(m["inquiry_mission_id"])
        if quotes_by_mission.get(mission_id) or not m.get("goods_supplier_name"):
            continue
        quote_rows.append((
            -mission_id, mission_id, m["goods_supplier_name"], None, None, None,
            m["goods_spec"], None, None, m["goods_quotation_type"],
            m["jh_goods_price"], m["jh_goods_price_has_tax"], None, None, None, 1,
        ))

    record_rows = []
    for m in missions:
        mission_id = int(m["inquiry_mission_id"])
        price, label = _pick_purchase_price(quotes_by_mission.get(mission_id, []), m)
        record_rows.append((
            mission_id, m["order_goods_id"], m["mission_sn"], m["mission_type"],
            m["used_time"], m["goods_name"], m["model"], m["goods_spec"], m["factory_name"],
            m["images"], m["goods_num"], m["invoice"], m["inquiry_time"],
            m["goods_describe"], price or None, m["quotation_type"],
            m["post_fee_purchase"], m["post_fee_has_tax_purchase"],
            label or None, m["quote_updated_at"],
            m["create_user"], m["create_time"],
        ))

    chat_rows = [
        (c["id"], c["order_goods_id"], c["content"], c["attachments"],
         c["creator"], c["create_time"])
        for c in chats
    ]
    payload = [
        ("inquiry_quotes", QUOTE_UPSERT, quote_rows),
        ("inquiry_records", RECORD_UPSERT, record_rows),
        ("inquiry_communications", CHAT_UPSERT, chat_rows),
    ]
    return payload, len(quote_rows) - len(quotes)


def table_counts(conn):
    cur = conn.cursor()
    counts = {}
    for table in TABLES:
        cur.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
        counts[table] = cur.fetchone()["n"]
    return counts


def write_env(name, config, payload):
    """写一个环境，返回 True/False。失败只影响这个环境。"""
    try:
        conn = connect(config)
    except Exception as exc:
        log.error(f"[{name}] 连接 {describe(config)} 失败：{type(exc).__name__}: {exc}")
        return False
    log.info(f"[{name}] 写入 {describe(config)}")
    try:
        before = table_counts(conn)
        for table, sql, rows in payload:
            started = time.perf_counter()
            cur = conn.cursor()
            for i in range(0, len(rows), BATCH):
                cur.executemany(sql, rows[i:i + BATCH])
                conn.commit()
            log.info(f"[{name}]   {table:<24}提交 {len(rows):>7,} 行  {time.perf_counter() - started:.1f}s")
        after = table_counts(conn)
        # 提交行数每次都一样，只有这里的新增数能看出这次到底有没有新数据
        for table in TABLES:
            added = after[table] - before[table]
            log.info(
                f"[{name}]   {table:<24}库内 {before[table]:,} -> {after[table]:,}"
                f"  本次新增 {added:+,}"
            )
        return True
    except Exception as exc:
        log.error(f"[{name}] 写入失败：{type(exc).__name__}: {exc}")
        return False
    finally:
        conn.close()


def main():
    setup_logging()
    log.info("=" * 66)
    log.info("询价同步开始")
    log.info(f"[OA]   {describe(OA_DB)}")
    for name, config in ENVS:
        log.info(f"[{name}] {describe(config) if configured(config) else '未配置，跳过'}")
    log.info("=" * 66)
    started = time.perf_counter()

    missions = oa_query("询价任务", MISSION_SQL)
    mission_ids = {int(m["inquiry_mission_id"]) for m in missions}
    goods_ids = {int(m["order_goods_id"]) for m in missions if m.get("order_goods_id")}

    quotes = oa_query("明细报价", QUOTE_SQL)
    quotes = [
        q for q in quotes
        if q.get("mission_id") is not None and int(q["mission_id"]) in mission_ids
    ]
    log.info(f"[OA] 明细报价按本次任务过滤后 {len(quotes):,} 条")

    chats = oa_query("沟通记录", CHAT_SQL)
    chats = [c for c in chats if int(c["order_goods_id"] or 0) in goods_ids]
    log.info(f"[OA] 沟通记录按本次商品过滤后 {len(chats):,} 条")

    payload, filled = build_payload(missions, quotes, chats)
    log.info(f"[OA] 商品主行补报价 {filled:,} 条")

    results = []
    written = {}
    for name, config in ENVS:
        if not configured(config):
            log.warning(f"[{name}] 跳过：{name}库的 host/user 还没填")
            results.append((name, None))
            continue
        target = describe(config)
        if target in written:
            # 两个环境配成同一个库时没必要写第二遍
            log.warning(f"[{name}] 跳过：和「{written[target]}」是同一个库（{target}）")
            results.append((name, None))
            continue
        written[target] = name
        results.append((name, write_env(name, config, payload)))

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
