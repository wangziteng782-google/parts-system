"""临时：摸清 OA 沟通记录接口（QueryGoodsQa）的必填参数。"""
import json
import re
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


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Admin-Token", TOKEN)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
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


DEFAULTS = {
    "id": 0,
    "content": "自检测试沟通-请忽略",
    "order_goods_id": 0,
    "can_edit": 0,
    "attachments": "",
    "type": "",
}

print("== QueryGoodsQa/createOrEdit 参数探测 ==")
body = {"content": DEFAULTS["content"]}
for step in range(10):
    result = post("/QueryGoodsQa/createOrEdit", body)
    print(f"[{step}] keys={sorted(body)} -> {json.dumps(result, ensure_ascii=False)[:220]}")
    if str(result.get("code")) == "200":
        print(">>> 成功:", json.dumps(result.get("data"), ensure_ascii=False)[:300])
        break
    msg = str(result.get("msg", ""))
    m = re.search(r'Undefined array key "(\w+)"', msg) or re.search(r"Undefined array key '(\w+)'", msg)
    if not m:
        break
    key = m.group(1)
    if key in body:
        break
    body[key] = DEFAULTS.get(key, "")

print("\n== QueryGoodsQa/list 参数 ==")
for params in ({"order_goods_id": 119611}, {"order_goods_id": 119611, "page": 1, "limit": 3}):
    url = BASE + "/QueryGoodsQa/list?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, method="GET")
    req.add_header("Admin-Token", TOKEN)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
            d = data.get("data") or {}
            print(f"  {params} -> code={data.get('code')} count={d.get('count') if isinstance(d, dict) else d}")
            if isinstance(d, dict) and d.get("list"):
                print("    字段:", list(d["list"][0].keys()))
    except Exception as exc:
        print("  失败", exc)
