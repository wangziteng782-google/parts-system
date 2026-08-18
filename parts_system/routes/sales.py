"""销售商品查询：只读返回商品、规格和换算后的销售展示价格。"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, datetime
import os
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel
import pymysql

from ..bootstrap import app
from ..auth import get_current_user, get_current_user_id
from ..feedback import FEEDBACK_TYPE_LABELS
from ..config import IMAGE_FIELDS, logger
from ..model import get_db, get_oa_db
from ..util import parse_image_urls


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



class SalesFeedbackRequest(BaseModel):
    record_source: str
    parts_id: Optional[int] = None
    inquiry_mission_id: Optional[int] = None
    inquiry_goods_id: Optional[int] = None
    problem_types: list[str]
    description: str


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




def _record_sales_query(
    keyword: str,
) -> None:
    user = get_current_user() or {}
    user_name = user.get("nickname") or user.get("username")
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO sales_query_logs
                   (user_id, user_name, query_keyword)
               VALUES (%s,%s,%s)""",
            (
                get_current_user_id(),
                user_name,
                keyword,
            ),
        )
        conn.commit()
    except pymysql.err.ProgrammingError as exc:
        conn.rollback()
        if exc.args and exc.args[0] in {1054, 1146}:
            logger.warning("[销售查询日志] 表结构未初始化，跳过记录")
            return
        raise
    except Exception as exc:
        conn.rollback()
        logger.warning("[销售查询日志] 写入失败 | error=%s", exc)
    finally:
        conn.close()


def _hidden_inquiry_mission_ids() -> list[int]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT inquiry_mission_id
               FROM sales_inquiry_listing_status
               WHERE listing_status=0"""
        )
        return [
            int(row["inquiry_mission_id"])
            for row in cursor.fetchall()
            if row.get("inquiry_mission_id") is not None
        ]
    except pymysql.err.ProgrammingError as exc:
        if exc.args and exc.args[0] == 1146:
            logger.warning("[销售查询] 询价上下架状态表不存在，暂按全部上架处理")
            return []
        raise
    finally:
        conn.close()


def _sort_value(item: dict, sort: str):
    if sort in {"default", "updated_desc"}:
        value = item.get("quote_updated_at")
        if isinstance(value, (datetime, date)):
            return value.isoformat(sep=" ")
        return str(value or "")
    price = item.get(
        "display_price_max" if sort == "price_desc" else "display_price_min",
        item.get("display_price"),
    )
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
    # 有效规格组合时，每个组合取标记为对外展示的供应商；
    # 未标记时回退到该组合最早保存的供应商，并汇总价格区间；
    # 不含票价 -> 含专票价 -> 含普票价选择第一个正数价格；
    # 没有有效规格组合时，才使用 parts.purchase_cost。

    # where条件 用来筛选是否有规格报价
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
    # 当前商品p 有没有至少一个有效规格价格 返回结果是否存在 true 和 false
    has_valid_variant_sql = (
        f"EXISTS (SELECT 1 FROM product_variant_prices candidate "
        f"WHERE {valid_variant_filter})"
    )
    # 在valid_variant_filter的基础上，筛选出最佳的价格记录
    preferred_variant_filter = (
        f"{valid_variant_filter} AND NOT EXISTS ("
        "SELECT 1 FROM product_variant_prices preferred "
        "WHERE preferred.part_id=candidate.part_id "
        "AND preferred.variant_group_id=candidate.variant_group_id "
        "AND (COALESCE(preferred.is_external_visible,0) "
        "> COALESCE(candidate.is_external_visible,0) "
        "OR (COALESCE(preferred.is_external_visible,0) "
        "= COALESCE(candidate.is_external_visible,0) "
        "AND preferred.id<candidate.id)))"
    )
    # 规格报价优先使用不含税价，没有不含税价就使用专票价，再没有就使用普票价。
    variant_price_sql = (
        "COALESCE(NULLIF(candidate.no_tax_price,0), "
        "NULLIF(candidate.purchase_special_invoice,0), "
        "NULLIF(candidate.purchase_general_invoice,0))"
    )
    # 找最低报价
    min_variant_quote_sql = (
        f"(SELECT MIN({variant_price_sql}) FROM product_variant_prices candidate "
        f"WHERE {preferred_variant_filter})"
    )
    # 找最低报价
    max_variant_quote_sql = (
        f"(SELECT MAX({variant_price_sql}) FROM product_variant_prices candidate "
        f"WHERE {preferred_variant_filter})"
    )
    def variant_invoice_bound(field: str, aggregate: str) -> str:
        return (
            f"(SELECT {aggregate}(NULLIF(candidate.{field},0)) "
            "FROM product_variant_prices candidate "
            f"WHERE {preferred_variant_filter})"
        )

    def parts_invoice_value(field: str) -> str:
        return (
            f"CASE WHEN TRIM(p.{field}) REGEXP '^[0-9]+([.][0-9]+)?$' "
            f"THEN CAST(TRIM(p.{field}) AS DECIMAL(14,2)) ELSE NULL END"
        )

    invoice_bounds = {}
    for field in ("purchase_special_invoice", "purchase_general_invoice"):
        parts_value = parts_invoice_value(field)
        invoice_bounds[field] = {
            "min": (
                f"CASE WHEN {has_valid_variant_sql} "
                f"THEN {variant_invoice_bound(field, 'MIN')} ELSE NULLIF({parts_value},0) END"
            ),
            "max": (
                f"CASE WHEN {has_valid_variant_sql} "
                f"THEN {variant_invoice_bound(field, 'MAX')} ELSE NULLIF({parts_value},0) END"
            ),
            "available": (
                f"CASE WHEN {has_valid_variant_sql} THEN EXISTS ("
                "SELECT 1 FROM product_variant_prices candidate "
                f"WHERE {preferred_variant_filter} AND candidate.{field}=0) "
                f"ELSE COALESCE({parts_value}=0,0) END"
            ),
        }
    parts_purchase_cost_sql = (
        "CASE WHEN TRIM(p.purchase_cost) REGEXP '^[0-9]+([.][0-9]+)?' "
        "THEN CAST(TRIM(p.purchase_cost) AS DECIMAL(14,2)) ELSE NULL END"
    )
    # 有规格报价时使用规格报价 否则就用 parts.purchase_cost
    base_cost_min_sql = (
        f"(CASE WHEN {has_valid_variant_sql} THEN {min_variant_quote_sql} "
        f"ELSE {parts_purchase_cost_sql} END)"
    )
    base_cost_max_sql = (
        f"(CASE WHEN {has_valid_variant_sql} THEN {max_variant_quote_sql} "
        f"ELSE {parts_purchase_cost_sql} END)"
    )
    order_sql = {
        "default": "COALESCE(MAX(v.update_time), p.update_time_2, p.update_time) DESC, p.id DESC",
        "updated_desc": "COALESCE(MAX(v.update_time), p.update_time_2, p.update_time) DESC, p.id DESC",
        "price_asc": f"({base_cost_min_sql} IS NULL), {base_cost_min_sql} ASC, p.id DESC",
        "price_desc": f"({base_cost_max_sql} IS NULL), {base_cost_max_sql} DESC, p.id DESC",
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
            "completion.complete_id", "completion.change_id",
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
                       {image_columns}, {base_cost_min_sql} AS base_cost_min,
                       {base_cost_max_sql} AS base_cost_max,
                       {invoice_bounds['purchase_special_invoice']['min']} AS special_invoice_min,
                       {invoice_bounds['purchase_special_invoice']['max']} AS special_invoice_max,
                       {invoice_bounds['purchase_special_invoice']['available']} AS special_invoice_available,
                       {invoice_bounds['purchase_general_invoice']['min']} AS general_invoice_min,
                       {invoice_bounds['purchase_general_invoice']['max']} AS general_invoice_max,
                       {invoice_bounds['purchase_general_invoice']['available']} AS general_invoice_available,
                       {has_valid_variant_sql} AS has_variant_quotes,
                       CASE WHEN COALESCE(completion.complete_id,0)
                                      > COALESCE(completion.change_id,0)
                            THEN 1 ELSE 0 END AS modification_completed,
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
                LEFT JOIN (
                    SELECT part_id,
                           MAX(CASE WHEN operation_type='COMPLETE' THEN id END) AS complete_id,
                           MAX(CASE WHEN operation_type IN ('CREATE','UPDATE') THEN id END) AS change_id
                    FROM employee_operation_logs
                    GROUP BY part_id
                ) completion ON completion.part_id=p.id
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
                    row.get("base_cost_min"),
                    row.get("product_name"),
                    row.get("product_type"),
                ),
                "display_price_min": _display_price(
                    row.get("base_cost_min"),
                    row.get("product_name"),
                    row.get("product_type"),
                ),
                "display_price_max": _display_price(
                    row.get("base_cost_max"),
                    row.get("product_name"),
                    row.get("product_type"),
                ),
                "invoice_quote_summary": {
                    "has_variant_quotes": bool(row.get("has_variant_quotes")),
                    "special_min": _scaled_positive_price(
                        row.get("special_invoice_min"),
                        row.get("product_name"),
                        row.get("product_type"),
                    ),
                    "special_max": _scaled_positive_price(
                        row.get("special_invoice_max"),
                        row.get("product_name"),
                        row.get("product_type"),
                    ),
                    "special_available": bool(row.get("special_invoice_available")),
                    "general_min": _scaled_positive_price(
                        row.get("general_invoice_min"),
                        row.get("product_name"),
                        row.get("product_type"),
                    ),
                    "general_max": _scaled_positive_price(
                        row.get("general_invoice_max"),
                        row.get("product_name"),
                        row.get("product_type"),
                    ),
                    "general_available": bool(row.get("general_invoice_available")),
                },
                "modification_completed": bool(row.get("modification_completed")),
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
    hidden_ids = _hidden_inquiry_mission_ids()
    if hidden_ids:
        placeholders = ",".join(["%s"] * len(hidden_ids))
        where.append(f"m.id NOT IN ({placeholders})")
        params.extend(hidden_ids)
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
    conn = get_oa_db()
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
                "inquiry_mission_id": row["id"],
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
                "modification_completed": False,
                "quote_updated_at": row.get("quote_updated_at"),
                "record_source": "inquiry",
                "record_source_label": "来自询价记录",
            })
        return total, items
    finally:
        conn.close()


def _fetch_inquiry_communications(order_goods_id: int) -> list:
    conn = get_oa_db()
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
    """每个有效规格组合优先返回对外供应商，否则返回最早保存的供应商。"""
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
                      price.is_external_visible,
                      price.no_tax_price,
                       price.purchase_special_invoice,
                       price.purchase_general_invoice,
                       price.purchase_shipping, price.freight_remark,
                       price.shipping_origin, price.shipping_time,
                       price.warranty_time, price.daily_order_time,
                       price.quote_time, price.expire_date,
                       price.remark, price.update_time,
                       GROUP_CONCAT(
                          CONCAT(spec.spec_name, '：', spec.spec_value)
                          ORDER BY link.sort_order, link.id SEPARATOR '；'
                      ) AS specification,
                      MIN(link.id) AS first_link_id
                 FROM (
                      SELECT candidate.variant_group_id,
                             candidate.id AS first_price_id
                        FROM product_variant_prices candidate
                       WHERE candidate.part_id=%s
                         AND NOT EXISTS (
                             SELECT 1
                               FROM product_variant_prices preferred
                              WHERE preferred.part_id=candidate.part_id
                                AND preferred.variant_group_id=candidate.variant_group_id
                                AND (
                                    COALESCE(preferred.is_external_visible,0)
                                        > COALESCE(candidate.is_external_visible,0)
                                    OR (
                                        COALESCE(preferred.is_external_visible,0)
                                            = COALESCE(candidate.is_external_visible,0)
                                        AND preferred.id < candidate.id
                                    )
                                )
                         )
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
                         price.is_external_visible,
                          price.no_tax_price,
                          price.purchase_special_invoice,
                          price.purchase_general_invoice,
                          price.purchase_shipping, price.freight_remark,
                          price.shipping_origin, price.shipping_time,
                          price.warranty_time, price.daily_order_time,
                          price.quote_time, price.expire_date,
                          price.remark, price.update_time
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
                "is_external_visible": bool(row.get("is_external_visible")),
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
                 "purchase_shipping": _plain_business_value(
                     row.get("purchase_shipping")
                 ),
                 "freight_remark": row.get("freight_remark"),
                 "shipping_origin": row.get("shipping_origin"),
                 "shipping_time": row.get("shipping_time"),
                 "warranty_time": row.get("warranty_time"),
                 "daily_order_time": row.get("daily_order_time"),
                 "quote_time": row.get("quote_time"),
                 "expire_date": row.get("expire_date"),
                 "quote_remark": row.get("remark"),
                 "update_time": row.get("update_time"),
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
    response_data = {
        "items": merged[offset:offset + page_size],
        "total": parts_total + inquiry_total,
        "parts_total": parts_total,
        "inquiry_total": inquiry_total,
        "oa_available": oa_available,
        "page": page,
        "page_size": page_size,
    }
    if keyword:
        _record_sales_query(keyword)
    return response_data


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
    """每个有效规格组合优先返回对外供应商及其销售参考价。"""
    if part_id <= 0:
        raise HTTPException(status_code=400, detail="无效的配件 ID")
    return _fetch_parts_variant_quotes(part_id)


@app.post("/api/sales/feedback")
async def create_sales_feedback(req: SalesFeedbackRequest):
    """保存销售在商品详情中提交的问题反馈。"""
    source = str(req.record_source or "").strip().lower()
    if source not in {"parts", "inquiry"}:
        raise HTTPException(status_code=400, detail="商品来源无效")

    description = str(req.description or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="请输入具体错误描述")
    if len(description) > 2000:
        raise HTTPException(status_code=400, detail="错误描述不能超过2000字")

    normalized_types = []
    for problem_type in req.problem_types or []:
        code = str(problem_type or "").strip().lower()
        if code not in FEEDBACK_TYPE_LABELS:
            raise HTTPException(status_code=400, detail="包含不支持的问题类型")
        if code not in normalized_types:
            normalized_types.append(code)
    if not normalized_types:
        raise HTTPException(status_code=400, detail="请至少选择一项问题类型")

    parts_id = req.parts_id if req.parts_id and req.parts_id > 0 else None
    inquiry_goods_id = (
        req.inquiry_goods_id
        if req.inquiry_goods_id and req.inquiry_goods_id > 0
        else None
    )
    inquiry_mission_id = (
        req.inquiry_mission_id
        if req.inquiry_mission_id and req.inquiry_mission_id > 0
        else None
    )
    if source == "parts" and parts_id is None:
        raise HTTPException(status_code=400, detail="配件库反馈缺少parts_id")
    if source == "inquiry" and (inquiry_goods_id is None or inquiry_mission_id is None):
        raise HTTPException(status_code=400, detail="询价反馈缺少询价任务ID")
    conn = get_db()
    try:
        cursor = conn.cursor()
        if parts_id is not None:
            cursor.execute("SELECT id FROM parts WHERE id=%s", (parts_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="关联配件不存在")
        cursor.execute(
            """INSERT INTO sales_product_feedback
                   (parts_id, inquiry_mission_id, inquiry_goods_id,
                    feedback_user_id, source_type,
                    issue_types, description, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'pending')""",
            (
                parts_id,
                inquiry_mission_id,
                inquiry_goods_id,
                get_current_user_id(),
                source,
                ",".join(normalized_types),
                description,
            ),
        )
        feedback_id = int(cursor.lastrowid)
        conn.commit()
        logger.info(
            "[销售反馈] 提交成功 | feedback_id=%s | user_id=%s | source=%s | parts_id=%s | inquiry_mission_id=%s | inquiry_goods_id=%s",
            feedback_id,
            get_current_user_id(),
            source,
            parts_id,
            inquiry_mission_id,
            inquiry_goods_id,
        )
        return {"message": "反馈提交成功", "feedback_id": feedback_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        logger.exception("[销售反馈] 提交失败 | error=%s", exc)
        raise HTTPException(status_code=500, detail="反馈提交失败，请稍后重试") from exc
    finally:
        conn.close()
