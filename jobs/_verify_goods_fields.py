"""临时：验证 createOrEdit 是否保存型号/规格字段，并清理测试商品。"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pymysql

sys.stdout.reconfigure(encoding="utf-8")

TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
    "eyJpYXQiOjE3OTI1NDQ0NTYsIm5iZiI6MTc5MjU0NDQ1NiwiZXhwIjoxNzkyOTc2NDU2LCJkYXRhIjp7ImFk"
    "bWluX3VzZXJfaWQiOjEwNCwibG9naW5fdGltZSI6IjIwMjYtMTAtMjEgMDk6MDA6NTYiLCJsb2dpbl9pcCI6"
    "IjEyNC4yMzYuMTMyLjE4NSJ9fQ."
    "AeDEYrPC66-Dc_KBhwbWTu4NlzRRRrYKI4HNZpvb3rs"
)
BASE = "https://oa.yixiuti.com/admin"

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)

conn = pymysql.connect(
    host=os.getenv("OA_DB_HOST"), port=int(os.getenv("OA_DB_PORT", "3306")),
    user=os.getenv("OA_DB_USER"), password=os.getenv("OA_DB_PASSWORD"),
    database=os.getenv("OA_DB_NAME"), charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor, connect_timeout=8,
)


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Admin-Token", TOKEN)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8", "ignore"))
    except Exception as exc:
        return {"code": "ERR", "msg": str(exc)}


res = post("/QueryOrderGoods/createOrEdit", {
    "goods_name": "自检字段验证-请忽略",
    "goods_type": 1,
    "source": "",
    "inquiry_time": "",
    "package_id": "",
    "goods_num": 2,
    "send_address": "",
    "query_order_id": 0,
    "ele_type": "TEST-MODEL-001",
    "goods_spec": "AC220V 50HZ",
    "images": "",
})
gid = (res.get("data") or {}).get("id")
print("[创建]", json.dumps(res, ensure_ascii=False)[:200], "| id =", gid)

cur = conn.cursor()
cur.execute(
    "SELECT id, goods_name, ele_type, goods_spec, goods_num, goods_type, source, "
    "inquiry_time, package_id, send_address, query_order_id FROM yh_query_order_goods WHERE id=%s",
    (gid,),
)
print("[库内实际]", cur.fetchone())

cur.execute(
    "DELETE FROM yh_query_order_goods WHERE id IN (119648, %s) AND query_order_id=0",
    (gid,),
)
conn.commit()
print("[已清理测试商品] 影响", cur.rowcount, "条")
conn.close()
