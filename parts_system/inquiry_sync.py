"""把 OA 的询价任务、明细报价、沟通记录同步到本地三张落地表。

用法：
    python -m parts_system.inquiry_sync

顺序是明细报价 -> 询价记录（要用成交明细算价）-> 沟通记录。
全部 ON DUPLICATE KEY UPDATE，可以重复执行。
"""
import time
from collections import defaultdict

from .model import get_db, get_oa_db
from .routes.inquiry_match import _pick_purchase_price

BATCH = 500
RETRIES = 3

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


def oa_query(sql, params=()):
    for attempt in range(RETRIES):
        conn = None
        try:
            conn = get_oa_db()
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()
        except Exception as exc:
            if attempt == RETRIES - 1:
                raise
            print(f"  RETRY {attempt + 1} {type(exc).__name__}")
            time.sleep(3)
        finally:
            if conn:
                conn.close()


def _upsert(conn, sql, rows, label):
    if not rows:
        print(f"{label}: 0")
        return 0
    cur = conn.cursor()
    done = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        cur.executemany(sql, chunk)
        conn.commit()
        done += len(chunk)
    print(f"{label}: {done}")
    return done


def sync_all():
    """从 OA 全量拉取已完成询价，覆盖写入本地三张表。返回各表写入行数。"""
    print("1/4 拉取 OA 询价任务...")
    missions = oa_query(MISSION_SQL)
    print(f"  任务 {len(missions)} 条")
    goods_ids = {int(m["order_goods_id"]) for m in missions if m.get("order_goods_id")}
    mission_ids = {int(m["inquiry_mission_id"]) for m in missions}

    print("2/4 拉取 OA 明细报价...")
    quotes = oa_query(QUOTE_SQL)
    quotes = [
        q for q in quotes
        if q.get("mission_id") is not None and int(q["mission_id"]) in mission_ids
    ]
    print(f"  报价 {len(quotes)} 条")

    print("3/4 拉取 OA 沟通记录...")
    chats = oa_query(CHAT_SQL)
    chats = [c for c in chats if int(c["order_goods_id"] or 0) in goods_ids]
    print(f"  沟通 {len(chats)} 条（已按本次商品过滤）")

    quotes_by_mission = defaultdict(list)
    for q in quotes:
        quotes_by_mission[int(q["mission_id"])].append(q)

    conn = get_db()
    try:
        print("4/4 写入本地...")
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
        print(f"  其中商品主行补齐 {len(quote_rows) - len(quotes)} 条")
        quote_count = _upsert(conn, QUOTE_UPSERT, quote_rows, "inquiry_quotes")

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
        record_count = _upsert(conn, RECORD_UPSERT, record_rows, "inquiry_records")

        chat_count = _upsert(conn, CHAT_UPSERT, [
            (c["id"], c["order_goods_id"], c["content"], c["attachments"],
             c["creator"], c["create_time"])
            for c in chats
        ], "inquiry_communications")
        return {
            "inquiry_records": record_count,
            "inquiry_quotes": quote_count,
            "inquiry_communications": chat_count,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    result = sync_all()
    print("完成", result)
