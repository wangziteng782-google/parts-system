"""parts-system 电梯配件管理系统 MCP 连接器。

把 FastAPI 后端（http://127.0.0.1:8055）的能力封装成 MCP 工具，
供 WorkBuddy 在对话中直接调用：
- 产品/供应商/分类/价格查询（只读）
- AI 讲解 / 对比 / 替代型号 / 询价匹配
- 产品新增 / 字段修改（写操作）

依赖：parts-system 服务需在 127.0.0.1:8055 运行。
"""

import json
import urllib.request
import urllib.error
import urllib.parse

from mcp.server.mcpserver import MCPServer

BASE_URL = "http://127.0.0.1:8055"

mcp = MCPServer("parts-system")


def _http(method: str, path: str, payload: dict | None = None) -> dict:
    """调用 parts-system API，返回 JSON 对象。"""
    url = BASE_URL + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")[:500]
        raise RuntimeError(f"parts-system 接口返回 HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"无法连接 parts-system 服务（{BASE_URL}），请确认服务已启动"
        ) from exc


def _stream_ai(path: str, payload: dict) -> str:
    """调用流式 AI 接口（SSE），聚合返回最终 content。"""
    url = BASE_URL + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    final = ""
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            buf = ""
            for raw in resp:
                buf += raw.decode("utf-8", "ignore")
                while "\n\n" in buf:
                    chunk, buf = buf.split("\n\n", 1)
                    event = "message"
                    data_str = ""
                    for line in chunk.split("\n"):
                        if line.startswith("event:"):
                            event = line[6:].strip()
                        elif line.startswith("data:"):
                            data_str += line[5:].strip()
                    if event == "done" and data_str:
                        try:
                            obj = json.loads(data_str)
                            final = obj.get("content", "")
                        except Exception:
                            pass
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"AI 接口返回 HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"无法连接 parts-system 服务（{BASE_URL}），请确认服务已启动"
        ) from exc
    return final


def _query(params: dict) -> str:
    return "&".join(
        f"{urllib.parse.quote(str(k))}={urllib.parse.quote(str(v))}"
        for k, v in params.items()
        if v is not None and v != ""
    )


# ===================== 只读查询 =====================

@mcp.tool()
def search_products(
    keyword: str = "",
    category: str = "",
    product_type: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询配件产品列表（分页）。keyword 按名称/型号/SKU/品牌模糊搜索；category 按品类；product_type 按三级分类。"""
    qs = _query({
        "keyword": keyword, "category": category, "product_type": product_type,
        "page": page, "page_size": page_size,
    })
    return _http("GET", f"/api/products?{qs}")


@mcp.tool()
def get_product(product_id: int) -> dict:
    """查询单个产品的完整详情。"""
    return _http("GET", f"/api/products/{product_id}")


@mcp.tool()
def list_suppliers() -> list:
    """列出所有供应商（parts 表 + 变体价格表去重）。"""
    return _http("GET", "/api/suppliers")


@mcp.tool()
def list_categories() -> dict:
    """列出产品分类树。"""
    return _http("GET", "/api/categories")


@mcp.tool()
def get_product_prices(product_id: int) -> list:
    """查询某产品的所有规格变体价格（含供应商、成本、专票/普票、运费等）。"""
    return _http("GET", f"/api/products/{product_id}/variant-prices")


@mcp.tool()
def search_sales_products(
    keyword: str = "",
    sort: str = "default",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询销售端商品（含销售参考价），同时查配件库和历史询价记录。sort 可选 default/updated_desc/price_asc/price_desc。"""
    qs = _query({"keyword": keyword, "sort": sort, "page": page, "page_size": page_size})
    return _http("GET", f"/api/sales/products?{qs}")


@mcp.tool()
def search_inquiries(keyword: str = "", status: str = "pending", page: int = 1, page_size: int = 20) -> dict:
    """查询询价记录列表。status 可选 pending/listed/hidden/all。"""
    qs = _query({"keyword": keyword, "status": status, "page": page, "page_size": page_size})
    return _http("GET", f"/api/inquiries?{qs}")


@mcp.tool()
def search_logs(
    keyword: str = "",
    operation: str = "",
    user_id: int = 0,
    module: str = "",
    start_date: str = "",
    end_date: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询操作日志。operation 可选 create/update/delete/complete/corrected；start_date/end_date 格式 YYYY-MM-DD。"""
    qs = _query({
        "keyword": keyword, "operation": operation, "user_id": user_id or None,
        "module": module, "start_date": start_date, "end_date": end_date,
        "page": page, "page_size": page_size,
    })
    return _http("GET", f"/api/logs?{qs}")


@mcp.tool()
def list_log_users() -> list:
    """列出操作日志涉及的用户。"""
    return _http("GET", "/api/logs/users")


@mcp.tool()
def get_log(log_id: int) -> dict:
    """查询单条操作日志详情。"""
    return _http("GET", f"/api/logs/{log_id}")


@mcp.tool()
def get_product_classifications() -> dict:
    """获取产品分类树（大类 → 类 → 具体配件）。"""
    return _http("GET", "/api/product-classifications")


@mcp.tool()
def get_field_labels() -> dict:
    """获取字段名到中文标签的映射。"""
    return _http("GET", "/api/field-labels")


@mcp.tool()
def get_product_variant_specs(product_id: int) -> list:
    """查询某产品的规格变体（成色/电压等规格维度）。"""
    return _http("GET", f"/api/products/{product_id}/variant-specs")


@mcp.tool()
def list_oa_suppliers() -> list:
    """列出 OA 供应商（含供应商 ID 和名称）。"""
    return _http("GET", "/api/oa/suppliers")


@mcp.tool()
def get_oa_supplier(supplier_id: int) -> dict:
    """查询单个 OA 供应商详情（含税率等）。"""
    return _http("GET", f"/api/oa/suppliers/{supplier_id}")


# ===================== AI 功能 =====================

@mcp.tool()
def ai_explain(
    product_name: str,
    model: str = "",
    product_brand: str = "",
    specification: str = "",
    product_type: str = "",
    display_price: str = "",
    warranty: str = "",
    shipping_origin: str = "",
    applicable_elevator_brand: str = "",
    technical_params: str = "",
) -> str:
    """AI 讲解：根据产品信息生成「安装位置/产品特点/销售话术」三段话术。"""
    return _stream_ai("/api/sales/ai-explain", {
        "product_name": product_name, "model": model or None,
        "product_brand": product_brand or None, "specification": specification or None,
        "product_type": product_type or None, "display_price": display_price or None,
        "warranty": warranty or None, "shipping_origin": shipping_origin or None,
        "applicable_elevator_brand": applicable_elevator_brand or None,
        "technical_params": technical_params or None,
    })


@mcp.tool()
def ai_compare(
    product_a_name: str = "",
    product_a_model: str = "",
    product_a_brand: str = "",
    product_a_price: str = "",
    product_b_name: str = "",
    product_b_model: str = "",
    product_b_brand: str = "",
    product_b_price: str = "",
) -> str:
    """AI 对比：对比两个配件，输出「差异对比/各自优势/推荐建议」。product_a_name 和 product_b_name 必填。"""
    if not product_a_name or not product_b_name:
        raise RuntimeError("product_a_name 和 product_b_name 必填")
    def _p(name, model, brand, price):
        return {
            "product_name": name, "model": model or None,
            "product_brand": brand or None, "display_price": price or None,
        }
    return _stream_ai("/api/sales/ai-compare", {
        "product_a": _p(product_a_name, product_a_model, product_a_brand, product_a_price),
        "product_b": _p(product_b_name, product_b_model, product_b_brand, product_b_price),
    })


@mcp.tool()
def ai_substitute(
    product_name: str,
    model: str = "",
    product_brand: str = "",
    specification: str = "",
    applicable_elevator_brand: str = "",
) -> str:
    """AI 替代型号：根据配件信息推荐可替代型号，输出「替代型号/替代理由」。"""
    return _stream_ai("/api/sales/ai-substitute", {
        "product_name": product_name, "model": model or None,
        "product_brand": product_brand or None, "specification": specification or None,
        "applicable_elevator_brand": applicable_elevator_brand or None,
    })


@mcp.tool()
def ai_match(text: str) -> str:
    """AI 询价匹配：解析客户需求描述，提取「搜索关键词/品牌/型号/品类」。"""
    return _stream_ai("/api/sales/ai-match", {"text": text})


# ===================== 写操作 =====================

@mcp.tool()
def create_product(fields: dict) -> dict:
    """新增产品（只写 parts 主表）。fields 支持：product_name/product_brand/model/supplier/warranty/applicable_elevator_brand/nature/substitute_model/precautions/product_type/technical_params/remark/purchase_cost/purchase_special_invoice/purchase_general_invoice/purchase_shipping 等。"""
    return _http("POST", "/api/products", {"fields": fields})


@mcp.tool()
def update_product_field(product_id: int, field: str, value: str) -> dict:
    """修改产品的单个字段。field 为字段名（如 purchase_cost、retail_price、supplier、remark 等）。"""
    return _http("PUT", f"/api/products/{product_id}", {"field": field, "value": value})


if __name__ == "__main__":
    import asyncio
    asyncio.run(mcp.run_stdio_async())
