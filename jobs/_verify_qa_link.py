"""临时：验证「商品 + 沟通记录」关联链路。"""
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
    "eyJpYXQiOjE3OTI1NDQ0NTYsIm5iZiI6MTc5MjU0NDQ1NiwiZXhwIjoxNzkyOTc2NDU2LCJkYXRhIjp7ImFk"
    "bWluX3VzZXJfaWQiOjEwNCwibG9naW5fdGltZSI6IjIwMjYtMTAtMjEgMDk6MDA6NTYiLCJsb2dpbl9pcCI6"
    "IjEyNC4yMzYuMTMyLjE4NSJ9fQ."
    "AeDEYrPC66-Dc_KBhwbWTu4NlzRRRrYKI4HNZpvb3rs"
)
BASE = "https://oa.yixiuti.com/admin"


def request(path, body=None, method="POST"):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Admin-Token", TOKEN)
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8", "ignore"))
        except Exception:
            return {"code": exc.code, "msg": "http error"}
    except Exception as exc:
        return {"code": "ERR", "msg": str(exc)}


print("[1] 建商品")
goods = request("/QueryOrderGoods/createOrEdit", {
    "goods_name": "自检测关联验证-请忽略",
    "goods_type": 1,
    "source": "",
    "inquiry_time": "",
    "package_id": "",
    "goods_num": 1,
    "send_address": "",
    "query_order_id": 0,
})
gid = (goods.get("data") or {}).get("id")
print("   ->", json.dumps(goods, ensure_ascii=False)[:220], "| goods_id =", gid)

if not gid:
    raise SystemExit(0)

print("\n[2] 建沟通记录（关联该商品）")
qa = request("/QueryGoodsQa/createOrEdit", {
    "content": "自检测试：该产品的询价沟通记录",
    "mission_id": "",
    "qa_id": "",
    "order_goods_id": gid,
    "package_id": "",
})
qid = (qa.get("data") or {}).get("id")
print("   ->", json.dumps(qa, ensure_ascii=False)[:220], "| qa_id =", qid)

print("\n[3] 按 order_goods_id 反查沟通记录")
res = request(f"/QueryGoodsQa/list?order_goods_id={gid}&page=1&limit=5", method="GET")
data = res.get("data") or {}
print("   count =", data.get("count"))
for item in (data.get("list") or [])[:3]:
    print("   ", {k: item.get(k) for k in ("id", "order_goods_id", "content", "admin_id", "create_time")})

print("\n[4] 清理这条测试沟通记录")
if qid:
    deleted = request("/QueryGoodsQa/delete", {"id": qid})
    print("   ->", json.dumps(deleted, ensure_ascii=False)[:200])

print("\n[保留] 待清理商品 id =", gid)
