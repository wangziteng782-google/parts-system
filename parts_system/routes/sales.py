"""销售商品查询：只读返回商品、规格和换算后的销售展示价格。"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, datetime
import os
from typing import Optional

from fastapi import HTTPException
import pymysql

from ..bootstrap import app
from ..shared import IMAGE_FIELDS, get_db, logger, parse_image_urls


# 配件库销售价系数。匹配优先级：产品名称 > 产品分类 > 默认系数。
# 后续扩展时只需要在对应字典中增加“名称: 系数”。
SALES_PRODUCT_NAME_MULTIPLIERS = {
    "制动器": Decimal("1.10"),
    "梯级链": Decimal("1.10"),
}
# 后续扩展时只需要在对应字典中增加“分类: 系数”。
SALES_PRODUCT_TYPE_MULTIPLIERS = {}
# 默认系数
DEFAULT_SALES_PRICE_MULTIPLIER = Decimal("1.15")

OA_DB_CONFIG = {
    "host": os.getenv("OA_DB_HOST", "120.46.152.222").strip(),
    "port": int(os.getenv("OA_DB_PORT", "3306")),
    "user": os.getenv("OA_DB_USER", "oa_yixiuti").strip(),
    "password": os.getenv("OA_DB_PASSWORD", ""),
    "database": os.getenv("OA_DB_NAME", "oa_yixiuti").strip(),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "connect_timeout": int(os.getenv("OA_DB_CONNECT_TIMEOUT", "5")),
    "read_timeout": int(os.getenv("OA_DB_READ_TIMEOUT", "12")),
}


def _sales_price_multiplier(product_name, product_type) -> Decimal:
    """按产品名称、产品分类依次匹配销售价系数。"""
    normalized_name = str(product_name or "").strip()
    normalized_type = str(product_type or "").strip()
    if normalized_name in SALES_PRODUCT_NAME_MULTIPLIERS:
        return SALES_PRODUCT_NAME_MULTIPLIERS[normalized_name]
    if normalized_type in SALES_PRODUCT_TYPE_MULTIPLIERS:
        return SALES_PRODUCT_TYPE_MULTIPLIERS[normalized_type]
    return DEFAULT_SALES_PRICE_MULTIPLIER


def _display_price(cost, product_name=None, product_type=None) -> Optional[str]:
    if cost is None or str(cost).strip() == "":
        return None
    try:
        amount = Decimal(str(cost).strip())
    except InvalidOperation:
        return None
    if amount < 0:
        return None
    return str(
        (amount * _sales_price_multiplier(product_name, product_type)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    )


def _scaled_positive_price(value, product_name, product_type) -> Optional[str]:
    """正数报价乘销售系数；空值、0和非数字不作为具体价格。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        if Decimal(str(value).strip()) <= 0:
            return None
    except InvalidOperation:
        return None
    return _display_price(value, product_name, product_type)


def _is_explicit_zero(value) -> bool:
    if value is None or str(value).strip() == "":
        return False
    try:
        return Decimal(str(value).strip()) == 0
    except InvalidOperation:
        return False


def _plain_business_value(value) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _first_product_image(row: dict) -> Optional[str]:
    for field in IMAGE_FIELDS:
        urls = parse_image_urls(row.get(field))
        if urls:
            return urls[0]
    return None


def _oa_image(value) -> Optional[str]:
    urls = parse_image_urls(value)
    return urls[0] if urls else None


def _oa_connection():
    if not OA_DB_CONFIG["password"]:
        raise RuntimeError("未配置 OA_DB_PASSWORD")
    return pymysql.connect(**OA_DB_CONFIG)


def _sort_value(item: dict, sort: str):
    if sort in {"default", "updated_desc"}:
        value = item.get("quote_updated_at")
        if isinstance(value, (datetime, date)):
            return value.isoformat(sep=" ")
        return str(value or "")
    price = item.get("display_price")
    if price is None:
        return None
    try:
        return Decimal(str(price))
    except InvalidOperation:
        return None


def _merge_sales_items(parts_items: list, inquiry_items: list, sort: str) -> list:
    items = [*parts_items, *inquiry_items]
    if sort == "price_asc":
        return sorted(
            items,
            key=lambda item: (
                _sort_value(item, sort) is None,
                _sort_value(item, sort) or Decimal("0"),
                -int(item["id"]),
            ),
        )
    if sort == "price_desc":
        return sorted(
            items,
            key=lambda item: (
                _sort_value(item, sort) is None,
                -(_sort_value(item, sort) or Decimal("0")),
                -int(item["id"]),
            ),
        )
    return sorted(
        items,
        key=lambda item: (_sort_value(item, sort), int(item["id"])),
        reverse=True,
    )


def _fetch_parts_products(keyword: str, sort: str, limit: int):
    where = ["COALESCE(TRIM(p.product_name), '') <> ''"]
    params = []
    if keyword:
        like_keyword = f"%{keyword}%"
        where.append(
            "(p.product_name LIKE %s OR p.model LIKE %s "
            "OR p.product_brand LIKE %s OR p.nature LIKE %s OR EXISTS ("
            "SELECT 1 FROM product_variant_specs search_spec "
            "WHERE search_spec.part_id=p.id AND search_spec.is_active=1 "
            "AND (search_spec.spec_name LIKE %s OR search_spec.spec_value LIKE %s)"
            "))"
        )
        params.extend([like_keyword] * 6)
    where_sql = " WHERE " + " AND ".join(where)
    # 列表销售参考价与详情价格表保持同一口径：
    # 有有效规格组合时，取第一个组合中最早保存的供应商，并按
    # 不含票价 -> 含专票价 -> 含普票价选择第一个正数价格；
    # 没有有效规格组合时，才使用 parts.purchase_cost。
    valid_variant_filter = (
        "candidate.part_id=p.id "
        "AND EXISTS ("
        "SELECT 1 FROM product_variant_group_specs candidate_link "
        "JOIN product_variant_specs candidate_spec ON candidate_spec.id=candidate_link.spec_id "
        "WHERE candidate_link.part_id=candidate.part_id "
        "AND candidate_link.variant_group_id=candidate.variant_group_id"
        ") "
        "AND NOT EXISTS ("
        "SELECT 1 FROM product_variant_group_specs inactive_link "
        "JOIN product_variant_specs inactive_spec ON inactive_spec.id=inactive_link.spec_id "
        "WHERE inactive_link.part_id=candidate.part_id "
        "AND inactive_link.variant_group_id=candidate.variant_group_id "
        "AND COALESCE(inactive_spec.is_active,0)<>1"
        ")"
    )
    has_valid_variant_sql = (
        f"EXISTS (SELECT 1 FROM product_variant_prices candidate "
        f"WHERE {valid_variant_filter})"
    )
    first_variant_quote_sql = (
        "(SELECT COALESCE(NULLIF(candidate.no_tax_price,0), "
        "NULLIF(candidate.purchase_special_invoice,0), "
        "NULLIF(candidate.purchase_general_invoice,0)) "
        "FROM product_variant_prices candidate "
        f"WHERE {valid_variant_filter} "
        "ORDER BY ("
        "SELECT MIN(order_link.id) FROM product_variant_group_specs order_link "
        "WHERE order_link.part_id=candidate.part_id "
        "AND order_link.variant_group_id=candidate.variant_group_id"
        "), candidate.id LIMIT 1)"
    )
    parts_purchase_cost_sql = (
        "CASE WHEN TRIM(p.purchase_cost) REGEXP '^[0-9]+([.][0-9]+)?' "
        "THEN CAST(TRIM(p.purchase_cost) AS DECIMAL(14,2)) ELSE NULL END"
    )
    base_cost_sql = (
        f"(CASE WHEN {has_valid_variant_sql} THEN {first_variant_quote_sql} "
        f"ELSE {parts_purchase_cost_sql} END)"
    )
    order_sql = {
        "default": "COALESCE(MAX(v.update_time), p.update_time_2, p.update_time) DESC, p.id DESC",
        "updated_desc": "COALESCE(MAX(v.update_time), p.update_time_2, p.update_time) DESC, p.id DESC",
        "price_asc": f"({base_cost_sql} IS NULL), {base_cost_sql} ASC, p.id DESC",
        "price_desc": f"({base_cost_sql} IS NULL), {base_cost_sql} DESC, p.id DESC",
    }[sort]
    image_columns = ", ".join(f"p.{field}" for field in IMAGE_FIELDS)
    detail_columns = [
        "sku_code", "supplier", "warranty", "applicable_elevator_brand",
        "substitute_model", "precautions", "technical_params", "remark",
        "daily_cutoff_time", "quote_validity", "shipping_origin", "shipping_time",
        "remark_2", "updater", "filler",
    ]
    part_price_columns = [
        "purchase_special_invoice", "purchase_general_invoice",
        "purchase_shipping",
    ]
    group_columns = ", ".join(
        [
            "p.id", "p.product_name", "p.model", "p.product_brand", "p.product_type",
            "p.nature", "p.purchase_cost", "p.update_time", "p.update_time_2",
            *[f"p.{field}" for field in detail_columns],
            *[f"p.{field}" for field in part_price_columns],
            *[f"p.{field}" for field in IMAGE_FIELDS],
        ]
    )
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM parts p" + where_sql, params)
        total = int(cursor.fetchone()["total"])
        cursor.execute(
            f"""SELECT p.id, p.product_name, p.model, p.product_brand, p.product_type,
                       p.nature, {", ".join(f"p.{field}" for field in detail_columns)},
                       {", ".join(f"p.{field}" for field in part_price_columns)},
                       {image_columns}, {base_cost_sql} AS base_cost,
                       COALESCE(
                           NULLIF(
                               (SELECT GROUP_CONCAT(
                                           CONCAT(spec.spec_name, '：', spec.spec_value)
                                           ORDER BY spec.sort_order, spec.id SEPARATOR '；'
                                       )
                                  FROM product_variant_specs spec
                                 WHERE spec.part_id=p.id
                                   AND spec.is_active=1
                                   AND COALESCE(TRIM(spec.spec_value), '') <> ''
                                   AND EXISTS (
                                       SELECT 1
                                         FROM product_variant_group_specs link
                                        WHERE link.part_id=p.id
                                          AND link.spec_id=spec.id
                                   )
                               ),
                               ''
                           ),
                           NULLIF(TRIM(p.nature), '')
                       ) AS specification,
                       COALESCE(MAX(v.update_time), p.update_time_2, p.update_time)
                           AS quote_updated_at
                FROM parts p
                LEFT JOIN product_variant_prices v ON v.part_id=p.id
                {where_sql}
                GROUP BY {group_columns}
                ORDER BY {order_sql}
                LIMIT %s""",
            [*params, limit],
        )
        items = []
        for row in cursor.fetchall():
            items.append({
                "id": row["id"],
                "product_name": row.get("product_name"),
                "model": row.get("model"),
                "specification": row.get("specification"),
                "product_brand": row.get("product_brand"),
                "product_type": row.get("product_type"),
                "nature": row.get("nature"),
                **{field: row.get(field) for field in detail_columns},
                "part_price_summary": {
                    "purchase_cost": _display_price(
                        row.get("purchase_cost"),
                        row.get("product_name"),
                        row.get("product_type"),
                    ),
                    "purchase_special_invoice": _plain_business_value(
                        row.get("purchase_special_invoice")
                    ),
                    "purchase_special_invoice_available": _is_explicit_zero(
                        row.get("purchase_special_invoice")
                    ),
                    "purchase_general_invoice": _plain_business_value(
                        row.get("purchase_general_invoice")
                    ),
                    "purchase_general_invoice_available": _is_explicit_zero(
                        row.get("purchase_general_invoice")
                    ),
                    "purchase_shipping": _plain_business_value(
                        row.get("purchase_shipping")
                    ),
                },
                "image": _first_product_image(row),
                "display_price": _display_price(
                    row.get("base_cost"),
                    row.get("product_name"),
                    row.get("product_type"),
                ),
                "quote_updated_at": row.get("quote_updated_at"),
                "record_source": "parts",
                "record_source_label": "来自配件库",
            })
        return total, items
    finally:
        conn.close()


def _fetch_inquiry_products(keyword: str, sort: str, limit: int):
    where = [
        "m.mission_type=1",
        "m.mission_status=4",
        "m.delete_time IS NULL",
    ]
    params = []
    if keyword:
        like_keyword = f"%{keyword}%"
        where.append(
            "(g.goods_name LIKE %s OR g.ele_type LIKE %s "
            "OR g.goods_spec LIKE %s OR f.factory_name LIKE %s)"
        )
        params.extend([like_keyword] * 4)
    where_sql = " WHERE " + " AND ".join(where)
    mission_price_sql = (
        "CASE WHEN TRIM(m.purchase_price) REGEXP '^[0-9]+([.][0-9]+)?' "
        "THEN CAST(TRIM(m.purchase_price) AS DECIMAL(12,2)) ELSE NULL END"
    )
    price_sql = (
        f"COALESCE(NULLIF({mission_price_sql},0), "
        "NULLIF(g.purchase_price,0), NULLIF(g.goods_price,0))"
    )
    updated_sql = (
        "COALESCE(m.renew_time, m.update_time, m.finish_time, m.create_time, "
        "g.quote_time, g.update_time, g.inquiry_time, g.create_time)"
    )
    order_sql = {
        "default": f"{updated_sql} DESC, m.id DESC",
        "updated_desc": f"{updated_sql} DESC, m.id DESC",
        "price_asc": f"({price_sql} IS NULL), {price_sql} ASC, m.id DESC",
        "price_desc": f"({price_sql} IS NULL), {price_sql} DESC, m.id DESC",
    }[sort]
    conn = _oa_connection()
    try:
        cursor = conn.cursor()
        from_sql = (
            " FROM yh_query_goods_mission m "
            "LEFT JOIN yh_query_order_goods g ON g.id=m.order_goods_id "
            "LEFT JOIN yh_factory f ON f.id=g.factory AND f.delete_time IS NULL"
        )
        cursor.execute("SELECT COUNT(*) AS total" + from_sql + where_sql, params)
        total = int(cursor.fetchone()["total"])
        cursor.execute(
            f"""SELECT m.id, m.order_goods_id, m.quotation_type, m.purchase_price,
                       m.post_fee_purchase, m.post_fee_has_tax_purchase,
                       g.goods_name, g.ele_type, g.goods_spec, g.images,
                       g.goods_describe, g.post_fee_describe, g.goods_price_tax,
                       g.address, g.goods_type, g.goods_num, g.goods_unit, g.tax_fee,
                       g.total_amount, g.remark, g.tax_rate, g.post_fee,
                       g.post_fee_tax_rate, g.post_fee_tax_fee, g.post_fee_has_tax,
                       g.ele_scene, g.inquiry_time, g.create_time,
                       {price_sql} AS display_price,
                       f.factory_name, {updated_sql} AS quote_updated_at
                {from_sql}
                {where_sql}
                ORDER BY {order_sql}
                LIMIT %s""",
            [*params, limit],
        )
        items = []
        for row in cursor.fetchall():
            price = row.get("display_price")
            items.append({
                "id": row["id"],
                "order_goods_id": row.get("order_goods_id"),
                "quotation_type": row.get("quotation_type"),
                "purchase_price": row.get("purchase_price"),
                "post_fee_purchase": row.get("post_fee_purchase"),
                "post_fee_has_tax_purchase": row.get("post_fee_has_tax_purchase"),
                "product_name": row.get("goods_name"),
                "model": row.get("ele_type"),
                "specification": row.get("goods_spec"),
                "product_brand": row.get("factory_name"),
                "nature": None,
                "goods_describe": row.get("goods_describe"),
                "post_fee_describe": row.get("post_fee_describe"),
                "goods_price_tax": row.get("goods_price_tax"),
                "address": row.get("address"),
                "goods_type": row.get("goods_type"),
                "goods_num": row.get("goods_num"),
                "goods_unit": row.get("goods_unit"),
                "tax_fee": row.get("tax_fee"),
                "total_amount": row.get("total_amount"),
                "remark": row.get("remark"),
                "tax_rate": row.get("tax_rate"),
                "post_fee": row.get("post_fee"),
                "post_fee_tax_rate": row.get("post_fee_tax_rate"),
                "post_fee_tax_fee": row.get("post_fee_tax_fee"),
                "post_fee_has_tax": row.get("post_fee_has_tax"),
                "ele_scene": row.get("ele_scene"),
                "inquiry_time": row.get("inquiry_time"),
                "create_time": row.get("create_time"),
                "image": _oa_image(row.get("images")),
                "display_price": None if price is None else str(price),
                "quote_updated_at": row.get("quote_updated_at"),
                "record_source": "inquiry",
                "record_source_label": "来自询价记录",
            })
        return total, items
    finally:
        conn.close()


def _fetch_inquiry_communications(order_goods_id: int) -> list:
    conn = _oa_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT qa.id, qa.content, qa.attachments, qa.create_time,
                      COALESCE(NULLIF(TRIM(u.nickname), ''), u.username) AS creator
                 FROM yh_query_goods_qa qa
                 LEFT JOIN yh_admin_user u ON u.id=qa.admin_id
                WHERE qa.order_goods_id=%s
                  AND qa.delete_time IS NULL
                ORDER BY qa.create_time ASC, qa.id ASC""",
            [order_goods_id],
        )
        return [
            {
                "id": row["id"],
                "content": row.get("content"),
                "attachments": parse_image_urls(row.get("attachments")),
                "creator": row.get("creator"),
                "create_time": row.get("create_time"),
            }
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def _fetch_parts_variant_quotes(part_id: int) -> dict:
    """按有效规格组合返回最早保存的供应商及乘系数后的销售参考价。"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, product_name, product_type FROM parts WHERE id=%s",
            [part_id],
        )
        part = cursor.fetchone()
        if not part:
            raise HTTPException(status_code=404, detail="配件不存在")

        cursor.execute(
            """SELECT price.id, price.variant_group_id, price.supplier,
                      price.purchase_cost, price.no_tax_price,
                      price.purchase_special_invoice,
                      price.purchase_general_invoice,
                      GROUP_CONCAT(
                          CONCAT(spec.spec_name, '：', spec.spec_value)
                          ORDER BY link.sort_order, link.id SEPARATOR '；'
                      ) AS specification,
                      MIN(link.id) AS first_link_id
                 FROM (
                      SELECT variant_group_id, MIN(id) AS first_price_id
                        FROM product_variant_prices
                       WHERE part_id=%s
                       GROUP BY variant_group_id
                 ) first_price
                 JOIN product_variant_prices price
                   ON price.id=first_price.first_price_id
                  AND price.part_id=%s
                 JOIN product_variant_group_specs link
                   ON link.part_id=price.part_id
                  AND link.variant_group_id=price.variant_group_id
                 JOIN product_variant_specs spec
                   ON spec.id=link.spec_id
                GROUP BY price.id, price.variant_group_id, price.supplier,
                         price.purchase_cost, price.no_tax_price,
                         price.purchase_special_invoice,
                         price.purchase_general_invoice
               HAVING MIN(spec.is_active)=1
                ORDER BY first_link_id, price.id""",
            [part_id, part_id],
        )
        multiplier = _sales_price_multiplier(
            part.get("product_name"),
            part.get("product_type"),
        )
        items = []
        for row in cursor.fetchall():
            items.append({
                "variant_group_id": row.get("variant_group_id"),
                "specification": row.get("specification"),
                "supplier": row.get("supplier"),
                "no_tax_price": _scaled_positive_price(
                    row.get("no_tax_price"),
                    part.get("product_name"),
                    part.get("product_type"),
                ),
                "special_invoice_price": _scaled_positive_price(
                    row.get("purchase_special_invoice"),
                    part.get("product_name"),
                    part.get("product_type"),
                ),
                "special_invoice_available": _is_explicit_zero(
                    row.get("purchase_special_invoice")
                ),
                "general_invoice_price": _scaled_positive_price(
                    row.get("purchase_general_invoice"),
                    part.get("product_name"),
                    part.get("product_type"),
                ),
                "general_invoice_available": _is_explicit_zero(
                    row.get("purchase_general_invoice")
                ),
            })
        return {"multiplier": str(multiplier), "items": items}
    finally:
        conn.close()


@app.get("/api/sales/products")
async def sales_products(
    keyword: str = "",
    sort: str = "default",
    page: int = 1,
    page_size: int = 20,
):
    """分页查询销售商品；任何响应都不包含原始成本价。"""
    page = max(1, page)
    page_size = min(48, max(1, page_size))
    keyword = keyword.strip()[:100]
    allowed_sorts = {"default", "updated_desc", "price_asc", "price_desc"}
    if sort not in allowed_sorts:
        raise HTTPException(status_code=400, detail="无效的排序方式")

    candidate_limit = page * page_size
    parts_total, parts_items = _fetch_parts_products(
        keyword, sort, candidate_limit
    )
    inquiry_total = 0
    inquiry_items = []
    oa_available = True
    try:
        inquiry_total, inquiry_items = _fetch_inquiry_products(
            keyword, sort, candidate_limit
        )
    except Exception as exc:
        oa_available = False
        logger.warning("[销售查询] OA询价库暂不可用，仅展示配件库 | error=%s", exc)

    merged = _merge_sales_items(parts_items, inquiry_items, sort)
    offset = (page - 1) * page_size
    return {
        "items": merged[offset:offset + page_size],
        "total": parts_total + inquiry_total,
        "parts_total": parts_total,
        "inquiry_total": inquiry_total,
        "oa_available": oa_available,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/sales/inquiry-communications")
async def sales_inquiry_communications(order_goods_id: int):
    """按询价商品 ID 返回未删除的沟通记录。"""
    if order_goods_id <= 0:
        raise HTTPException(status_code=400, detail="无效的询价商品 ID")
    try:
        items = _fetch_inquiry_communications(order_goods_id)
    except Exception as exc:
        logger.warning(
            "[销售查询] 沟通记录读取失败 | order_goods_id=%s | error=%s",
            order_goods_id,
            exc,
        )
        raise HTTPException(status_code=503, detail="沟通记录暂时无法读取") from exc
    return {"items": items}


@app.get("/api/sales/parts/{part_id}/variant-quotes")
async def sales_parts_variant_quotes(part_id: int):
    """返回每个有效规格组合的首个供应商及销售参考价。"""
    if part_id <= 0:
        raise HTTPException(status_code=400, detail="无效的配件 ID")
    return _fetch_parts_variant_quotes(part_id)
