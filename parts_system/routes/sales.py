"""销售查询模块

销售端首页（/sales）数据源：并列展示配件库产品与 OA 询价记录，
提供换算后的销售展示价、询价沟通记录查询、产品关联询价报价查询，
以及待改正反馈的提交接口。
"""

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
from ..model import get_db
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

# 定价模式 2：对外展示类型 → 销售价字段
RETAIL_PRICE_COLUMNS = {
    "no_tax": "retail_no_tax_price",
    "special": "retail_special_price",
    "general": "retail_general_price",
}



class SalesFeedbackRequest(BaseModel):
    record_source: str
    parts_id: Optional[int] = None
    inquiry_mission_id: Optional[int] = None
    inquiry_goods_id: Optional[int] = None
    problem_types: list[str]
    description: str


class SalesInquiryLinkRequest(BaseModel):
    """一键询价回写：把 OA 询价商品和当前 SPU/SKU 先绑上，mission 稍后回填。"""
    order_goods_id: int
    part_id: Optional[int] = None
    variant_group_id: Optional[str] = None


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


def _plain_price(value) -> Optional[str]:
    """原样输出两位小数，不乘销售系数。用于定价模式 2 的人工销售价。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    if amount < 0:
        return None
    return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


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


def _all_product_images(row: dict) -> list[str]:
    return list(dict.fromkeys(u for f in IMAGE_FIELDS for u in parse_image_urls(row.get(f))))


def _oa_image(value) -> Optional[str]:
    urls = parse_image_urls(value)
    return urls[0] if urls else None




def _record_sales_query(
    keyword: str,
    has_result: bool = True,
) -> None:
    user = get_current_user() or {}
    user_name = user.get("nickname") or user.get("username")
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO sales_query_logs
                   (user_id, user_name, query_keyword, has_result)
               VALUES (%s,%s,%s,%s)""",
            (
                get_current_user_id(),
                user_name,
                keyword,
                1 if has_result else 0,
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


def _collect_single_prices(cursor, ids: list[int]) -> dict[int, dict[str, float]]:
    """收集单规格产品的对外价格（按类型存储）"""
    prices: dict[int, dict[str, float]] = {}
    if not ids:
        return prices
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""SELECT pvp.part_id, pvp.no_tax_price, pvp.purchase_special_invoice,
                   pvp.purchase_general_invoice, pvp.external_price_fields,
                   pvp.supplier, pvp.retail_price,
                   pvp.retail_no_tax_price, pvp.retail_special_price, pvp.retail_general_price,
                   p.pricing_mode
            FROM product_variant_prices pvp
            JOIN parts p ON p.id=pvp.part_id
            WHERE pvp.part_id IN ({placeholders})
            ORDER BY pvp.part_id, pvp.id""",
        ids,
    )
    for row in cursor.fetchall():
        # 定价模式 2（商品库导入商品）：对外只展示人工维护的销售价，采购供应商报价一律不外露
        # 销售价行必须选了对外展示类型才露出，未选视为价格待完善
        if int(row.get('pricing_mode') or 1) == 2:
            sale_fields = [f for f in (row.get('external_price_fields') or '').split(',') if f]
            if not str(row.get('supplier') or '').strip():
                # 多选时列表主价按 不含票 > 含专票 > 含普票 取第一个有值的
                for field in ('no_tax', 'special', 'general'):
                    if field not in sale_fields:
                        continue
                    value = row.get(RETAIL_PRICE_COLUMNS[field])
                    if value is not None:
                        prices.setdefault(row["part_id"], {})['retail'] = float(value)
                        break
            continue
        fields = (row.get('external_price_fields') or '').split(',')
        p = prices.setdefault(row["part_id"], {})
        if 'no_tax' in fields and row.get('no_tax_price') is not None:
            p['no_tax'] = float(row['no_tax_price'])
        if 'special' in fields and row.get('purchase_special_invoice') is not None:
            p['special'] = float(row['purchase_special_invoice'])
        if 'general' in fields and row.get('purchase_general_invoice') is not None:
            p['general'] = float(row['purchase_general_invoice'])
        # 空供应商行存的是人工维护的销售价，不受 external_price_fields 控制
        if not str(row.get('supplier') or '').strip() and row.get('retail_price') is not None:
            p['retail'] = float(row['retail_price'])
    return prices


def _fetch_parts_rows(cursor, select_columns: str, where_clause: str, params: list, order_clause: str, limit=None):
    """查询产品行数据。where_clause 包含 WHERE 关键字，limit 为 None 时不限制。"""
    limit_sql = "" if limit is None else " LIMIT %s"
    limit_params = [] if limit is None else [limit]
    cursor.execute(
        f"""SELECT p.id, p.product_name, p.model, p.product_brand, p.product_type,
                   p.nature, p.update_time, p.update_time_2, p.pricing_mode,
                   {select_columns},
                   p.display_price_min, p.display_price_max,
                   COALESCE(vc.variant_count, 0) AS variant_count,
                   p.modification_completed,
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
                       AS quote_updated_at,
                   MAX(CASE WHEN p.pricing_mode=2 THEN (
                                 v.supplier=''
                                 AND (
                                     (FIND_IN_SET('no_tax', v.external_price_fields) AND v.retail_no_tax_price IS NOT NULL)
                                     OR (FIND_IN_SET('special', v.external_price_fields) AND v.retail_special_price IS NOT NULL)
                                     OR (FIND_IN_SET('general', v.external_price_fields) AND v.retail_general_price IS NOT NULL)
                                 ))
                             WHEN v.no_tax_price IS NOT NULL
                               OR v.purchase_special_invoice IS NOT NULL
                               OR v.purchase_general_invoice IS NOT NULL
                        THEN 1 ELSE 0 END) AS has_any_price,
                   MAX(CASE WHEN p.pricing_mode=2 THEN (
                                 v.supplier=''
                                 AND (
                                     (FIND_IN_SET('no_tax', v.external_price_fields) AND v.retail_no_tax_price IS NOT NULL AND v.retail_no_tax_price != 0)
                                     OR (FIND_IN_SET('special', v.external_price_fields) AND v.retail_special_price IS NOT NULL AND v.retail_special_price != 0)
                                     OR (FIND_IN_SET('general', v.external_price_fields) AND v.retail_general_price IS NOT NULL AND v.retail_general_price != 0)
                                 ))
                             WHEN (v.no_tax_price IS NOT NULL AND v.no_tax_price != 0)
                               OR (v.purchase_special_invoice IS NOT NULL AND v.purchase_special_invoice != 0)
                               OR (v.purchase_general_invoice IS NOT NULL AND v.purchase_general_invoice != 0)
                        THEN 1 ELSE 0 END) AS has_nonzero_price,
                   MIN(v.expire_date) AS expire_date
            FROM parts p
            LEFT JOIN product_variant_prices v ON v.part_id=p.id
            LEFT JOIN (
                SELECT part_id, COUNT(DISTINCT variant_group_id) AS variant_count
                FROM product_variant_prices
                GROUP BY part_id
            ) vc ON vc.part_id=p.id
            {where_clause}
            GROUP BY p.id
            ORDER BY {order_clause}{limit_sql}""",
        [*params, *limit_params],
    )
    return cursor.fetchall()


def _build_parts_item(row: dict, prices: dict, detail_columns: list[str]) -> dict:
    variant_count = row["variant_count"]
    # 定价模式 2：销售价由人工维护，直接取零售价原值，不乘销售系数
    pricing_mode = int(row.get("pricing_mode") or 1)
    retail = prices.get("retail") if pricing_mode == 2 else None
    if variant_count == 0:
        display_type = "no_variant"
        # 无任何报价记录：不对销售兜底采购成本价，前端展示“价格待完善”
        display_price = None
        display_price_min = None
        display_price_max = None
        no_tax_price = None
        special_price = None
        general_price = None
    elif variant_count == 1:
        display_type = "single_variant"
        display_price_min = None
        display_price_max = None
        if pricing_mode == 2:
            # 模式2 只对外展示人工销售价；没有售价就是价格待完善，不回落采购报价
            display_price = _plain_price(retail)
            no_tax_price = None
            special_price = None
            general_price = None
        else:
            display_price = _display_price(prices.get('no_tax') or prices.get('special') or prices.get('general'), row.get("product_name"), row.get("product_type"))
            # 详情页固定展示三种价格，主价要用不含票原值，不能用含票兜底后的 display_price
            no_tax_price = _display_price(prices.get('no_tax'), row.get("product_name"), row.get("product_type"))
            special_price = _display_price(prices.get('special'), row.get("product_name"), row.get("product_type"))
            general_price = _display_price(prices.get('general'), row.get("product_name"), row.get("product_type"))
    else:
        display_type = "multi_variant"
        display_price = None
        if pricing_mode == 2:
            display_price_min = _plain_price(row.get("display_price_min"))
            display_price_max = _plain_price(row.get("display_price_max"))
        else:
            display_price_min = _display_price(row.get("display_price_min"), row.get("product_name"), row.get("product_type"))
            display_price_max = _display_price(row.get("display_price_max"), row.get("product_name"), row.get("product_type"))
        no_tax_price = None
        special_price = None
        general_price = None
    return {
        "id": row["id"],
        "product_name": row.get("product_name"),
        "model": row.get("model"),
        "specification": row.get("specification"),
        "product_brand": row.get("product_brand"),
        "product_type": row.get("product_type"),
        "nature": row.get("nature"),
        **{field: row.get(field) for field in detail_columns},
        "image": _first_product_image(row),
        "images": _all_product_images(row),
        "display_type": display_type,
        "display_price": display_price,
        "display_price_min": display_price_min,
        "display_price_max": display_price_max,
        "no_tax_price": no_tax_price,
        "special_price": special_price,
        "general_price": general_price,
        "modification_completed": bool(row.get("modification_completed")),
        "quote_updated_at": row.get("quote_updated_at"),
        "has_any_price": bool(row.get("has_any_price")),
        "has_nonzero_price": bool(row.get("has_nonzero_price")),
        "expire_date": row.get("expire_date"),
        "record_source": "parts",
        "record_source_label": "来自配件库",
    }


def _strip_space(text: str) -> str:
    """去掉半角/全角空格，用于型号等字段的模糊比对。"""
    return text.replace(" ", "").replace("　", "")


def _fetch_parts_products(keyword: str, sort: str, limit: int):
    where = ["COALESCE(TRIM(p.product_name), '') <> ''", "p.status=1"]
    params = []
    if keyword:
        # 空格分词，词之间 AND：每个词都要在名称/型号/品牌/性质/规格值之一命中。
        # 这样「高盛 10mm」定位到高盛的 10mm 钢丝绳，而不是两个条件互不相干。
        # 规格名不参与（只搜规格值），否则搜「曳引机」会把规格名带「曳引机型号」的
        # 曳引轮、制动器全带出来，结果从 19 条膨胀到 259 条。
        # 两侧都去掉空格再比：库里有 542 个型号带空格（ECN 113 2048 16S15-58），
        # 用户不带空格输入（ECN113204816S15-58）也要能搜到。
        for token in keyword.split():
            like_token = f"%{token}%"
            where.append(
                f"(REPLACE(REPLACE(p.product_name,' ',''),'　','') LIKE %s "
                f"OR REPLACE(REPLACE(p.model,' ',''),'　','') LIKE %s "
                f"OR REPLACE(REPLACE(p.product_brand,' ',''),'　','') LIKE %s "
                f"OR p.nature LIKE %s "
                f"OR EXISTS (SELECT 1 FROM product_variant_specs sv "
                f"WHERE sv.part_id = p.id AND sv.is_active = 1 "
                f"AND REPLACE(REPLACE(sv.spec_value,' ',''),'　','') LIKE %s))"
            )
            params.extend([like_token] * 5)
    where_sql = " WHERE " + " AND ".join(where)

    order_sql = {
        "default": "p.update_time_2 DESC, p.id DESC",
        "updated_desc": "p.update_time_2 DESC, p.id DESC",
        "price_asc": "(p.display_price_min IS NULL), p.display_price_min ASC, p.id DESC",
        "price_desc": "(p.display_price_max IS NULL), p.display_price_max DESC, p.id DESC",
    }[sort]

    # 只返回销售详情页真正展示的商品维度字段；质保、发货地、发货时间、报价有效期、
    # 每日截单时间这些以 product_variant_prices 的报价行为准，商品主表不再带
    detail_columns = [
        "applicable_elevator_brand", "substitute_model", "precautions",
        "technical_params", "remark", "remark_2", "updater", "filler",
    ]
    part_price_columns = [
        "purchase_special_invoice", "purchase_general_invoice",
        "purchase_shipping",
    ]
    all_select_columns = ", ".join(
        [f"p.{field}" for field in detail_columns + part_price_columns + IMAGE_FIELDS]
    )
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM parts p" + where_sql, params)
        total = int(cursor.fetchone()["total"])

        rows = _fetch_parts_rows(cursor, all_select_columns, where_sql, params, order_sql, limit)
        single_prices = _collect_single_prices(cursor, [r["id"] for r in rows if r["variant_count"] == 1])
        items = [_build_parts_item(row, single_prices.get(row["id"], {}), detail_columns) for row in rows]

        # 名称或型号直接命中的不打标签，只有靠品牌/性质/规格等旁证字段命中的才标"替代品"
        if keyword and keyword.strip() and len(items) > 1:
            # 与 SQL 一致地去空格比较，否则型号带空格的商品会被误标成替代品
            tokens = [_strip_space(t) for t in keyword.lower().split()]
            for item in items:
                name = _strip_space((item.get("product_name") or "").lower())
                model = _strip_space((item.get("model") or "").lower())
                direct = any(tok in name or tok in model for tok in tokens)
                if (not direct
                        and item.get("record_source_label") == "来自配件库"):
                    item["record_source_label"] = "替代品"

        # 查询关联产品并作为独立 item 追加（双向关系）
        # 查询关联产品的相关逻辑
        if rows:
            all_ids = [r["id"] for r in rows]
            placeholders = ",".join(["%s"] * len(all_ids))
            cursor.execute(
                f"""SELECT r.related_product_id AS pid
                    FROM product_relations r
                    WHERE r.product_id IN ({placeholders})
                    AND r.related_product_id NOT IN ({placeholders})
                    UNION
                    SELECT r.product_id AS pid
                    FROM product_relations r
                    WHERE r.related_product_id IN ({placeholders})
                    AND r.product_id NOT IN ({placeholders})""",
                all_ids + all_ids + all_ids + all_ids,
            )
            related_ids = [row["pid"] for row in cursor.fetchall()]

            if related_ids:
                placeholders = ",".join(["%s"] * len(related_ids))
                related_rows = _fetch_parts_rows(cursor, all_select_columns, f" WHERE p.id IN ({placeholders}) AND p.status=1", related_ids, "p.id DESC", None)
                related_prices = _collect_single_prices(cursor, [r["id"] for r in related_rows if r["variant_count"] == 1])
                for row in related_rows:
                    item = _build_parts_item(row, related_prices.get(row["id"], {}), detail_columns)
                    item["record_source_label"] = "替代品"
                    items.append(item)
                total += len(related_rows)

        return total, items
    finally:
        conn.close()


def _fetch_variant_combinations(part_ids: list[int]) -> dict[int, list[dict]]:
    """批量获取多个商品的规格组合数据（含停产状态）"""
    if not part_ids:
        return {}
    conn = get_db()
    try:
        cur = conn.cursor()
        placeholders = ','.join(['%s'] * len(part_ids))
        cur.execute(
            f"""SELECT link.part_id, link.variant_group_id,
                       MAX(link.is_discontinued) AS is_discontinued,
                       GROUP_CONCAT(
                           CONCAT(spec.spec_name, '：', spec.spec_value)
                           ORDER BY link.sort_order SEPARATOR '；'
                       ) AS specification
                   FROM product_variant_group_specs link
                   JOIN product_variant_specs spec ON spec.id=link.spec_id
                   WHERE link.part_id IN ({placeholders})
                     AND spec.is_active = 1
                     AND COALESCE(TRIM(spec.spec_value), '') <> ''
                   GROUP BY link.part_id, link.variant_group_id
                   ORDER BY link.part_id, link.variant_group_id""",
            part_ids,
        )
        result: dict[int, list[dict]] = {}
        for row in cur.fetchall():
            result.setdefault(row['part_id'], []).append({
                'variant_group_id': row['variant_group_id'],
                'specification': row['specification'] or '',
                'is_discontinued': bool(row.get('is_discontinued')),
            })
        return result
    finally:
        conn.close()


def _fetch_inquiry_products(keyword: str, sort: str, limit: int):
    """销售主查询的询价记录来源，读本地 inquiry_records（由 inquiry_sync 同步）。

    2026-11-20：销售主查询已不展示询价记录，本函数暂未被调用，
    恢复时把 sales_products 里注释掉的调用放开即可。
    """
    where, params = [], []
    hidden_ids = _hidden_inquiry_mission_ids()
    if hidden_ids:
        placeholders = ",".join(["%s"] * len(hidden_ids))
        where.append(f"inquiry_mission_id NOT IN ({placeholders})")
        params.extend(hidden_ids)
    if keyword:
        like_keyword = f"%{keyword}%"
        where.append(
            "(product_name LIKE %s OR model LIKE %s "
            "OR specification LIKE %s OR product_brand LIKE %s)"
        )
        params.extend([like_keyword] * 4)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    # 排序用成本价原始值，展示价再乘销售系数，两者口径不同，排序结果可能与展示价不完全一致
    price_sql = (
        "CASE WHEN TRIM(purchase_price) REGEXP '^[0-9]+([.][0-9]+)?' "
        "THEN CAST(TRIM(purchase_price) AS DECIMAL(12,2)) ELSE NULL END"
    )
    updated_sql = "quote_updated_at"
    order_sql = {
        "default": f"{updated_sql} DESC, inquiry_mission_id DESC",
        "updated_desc": f"{updated_sql} DESC, inquiry_mission_id DESC",
        "price_asc": f"({price_sql} IS NULL), {price_sql} ASC, inquiry_mission_id DESC",
        "price_desc": f"({price_sql} IS NULL), {price_sql} DESC, inquiry_mission_id DESC",
    }[sort]
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM inquiry_records" + where_sql, params)
        total = int(cursor.fetchone()["total"])
        cursor.execute(
            f"""SELECT inquiry_mission_id AS id, order_goods_id, quotation_type,
                       purchase_price, post_fee_purchase, post_fee_has_tax_purchase,
                       product_name AS goods_name, model AS ele_type,
                       specification AS goods_spec, images,
                       goods_describe, goods_num,
                       inquiry_time, create_time, product_brand AS factory_name,
                       {price_sql} AS cost_price,
                       (SELECT q.purchase_price FROM inquiry_quotes q
                         WHERE q.mission_id = inquiry_records.inquiry_mission_id
                           AND q.is_selected = 1
                         ORDER BY q.id DESC LIMIT 1) AS sale_price,
                       {updated_sql} AS quote_updated_at
                FROM inquiry_records
                {where_sql}
                ORDER BY {order_sql}
                LIMIT %s""",
            [*params, limit],
        )
        items = []
        for row in cursor.fetchall():
            cost = row.get("cost_price")
            sale = row.get("sale_price")
            items.append({
                "id": row["id"],
                "inquiry_mission_id": row["id"],
                "order_goods_id": row.get("order_goods_id"),
                "quotation_type": row.get("quotation_type"),
                "post_fee_purchase": row.get("post_fee_purchase"),
                "post_fee_has_tax_purchase": row.get("post_fee_has_tax_purchase"),
                "product_name": row.get("goods_name"),
                "model": row.get("ele_type"),
                "specification": row.get("goods_spec"),
                "product_brand": row.get("factory_name"),
                "goods_describe": row.get("goods_describe"),
                "goods_num": row.get("goods_num"),
                "inquiry_time": row.get("inquiry_time"),
                "create_time": row.get("create_time"),
                "image": _oa_image(row.get("images")),
                # 优先用 OA 里选中那条的报价金额（已含利润系数），没有明细时才按销售系数换算
                "display_price": str(sale) if sale is not None else _display_price(cost, row.get("goods_name")),
                "modification_completed": False,
                "quote_updated_at": row.get("quote_updated_at"),
                "has_any_price": True,
                "has_nonzero_price": True,
                "record_source": "inquiry",
                "record_source_label": "来自询价记录",
            })
        return total, items
    finally:
        conn.close()


def _fetch_inquiry_communications(order_goods_id: int) -> list:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, content, attachments, creator, create_time
                 FROM inquiry_communications
                WHERE order_goods_id=%s
                ORDER BY create_time ASC, id ASC""",
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
    """每个有效规格组合优先返回对外供应商，否则返回最早保存的供应商。
    同一规格组合存在多条供应商记录时，按 external_price_fields 合并各价格。"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, product_name, product_type, pricing_mode FROM parts WHERE id=%s",
            [part_id],
        )
        part = cursor.fetchone()
        if not part:
            raise HTTPException(status_code=404, detail="配件不存在")
        pricing_mode = int(part.get("pricing_mode") or 1)
        # 模式2 的销售价专用行（supplier 为空）也要进来，否则只有售价的商品选不到规格
        supplier_filter = "" if pricing_mode == 2 else " AND price.supplier <> ''"

        # 取出该 part 下所有有效规格组合的完整记录（含 external_price_fields）
        cursor.execute(
            f"""SELECT price.id, price.variant_group_id, price.supplier,
                      price.is_external_visible,
                      price.no_tax_price,
                      price.purchase_special_invoice,
                      price.purchase_general_invoice,
                      price.purchase_shipping, price.freight_remark,
                      price.shipping_origin, price.shipping_time,
                      price.warranty_time, price.daily_order_time,
                      price.quote_time, price.expire_date,
                      price.remark, price.update_time,
                      price.external_price_fields,
                      MAX(link.is_discontinued) AS is_discontinued,
                      GROUP_CONCAT(
                         CONCAT(spec.spec_name, '：', spec.spec_value)
                         ORDER BY link.sort_order, link.id SEPARATOR '；'
                      ) AS specification,
                      MIN(link.id) AS first_link_id
                 FROM product_variant_prices price
                 JOIN product_variant_group_specs link
                   ON link.part_id=price.part_id
                  AND link.variant_group_id=price.variant_group_id
                 JOIN product_variant_specs spec
                   ON spec.id=link.spec_id
                WHERE price.part_id=%s{supplier_filter}
                GROUP BY price.id
               HAVING MIN(spec.is_active)=1
                ORDER BY price.variant_group_id, price.id""",
            [part_id],
        )
        all_records = cursor.fetchall()

        # 按 variant_group_id 分组，合并价格
        groups: dict[int, list] = {}
        for rec in all_records:
            gid = rec.get("variant_group_id")
            groups.setdefault(gid, []).append(rec)

        items = []
        for gid in sorted(groups.keys()):
            records = groups[gid]
            # 主记录：is_external_visible 最高，其次 id 最小
            main = max(records, key=lambda r: (
                int(r.get("is_external_visible") or 0),
                -int(r.get("id") or 0),
            ))
            items.append(_merge_variant_prices(main, records, part))

        multiplier = _sales_price_multiplier(
            part.get("product_name"),
            part.get("product_type"),
        )
        result = {"multiplier": str(multiplier), "items": items}
        if pricing_mode == 2:
            # 模式2：对外价就是人工维护的销售价，按销售价选的对外展示类型落到对应价格上
            cursor.execute(
                """SELECT variant_group_id, retail_price,
                          retail_no_tax_price, retail_special_price, retail_general_price,
                          retail_invoice_company, retail_tax_rate, external_price_fields
                     FROM product_variant_prices
                    WHERE part_id=%s AND supplier=''""",
                [part_id],
            )
            retail_map = {r["variant_group_id"]: r for r in cursor.fetchall()}
            price_targets = {
                "no_tax": "no_tax_price",
                "special": "special_invoice_price",
                "general": "general_invoice_price",
            }
            for item in items:
                sale_row = retail_map.get(item["variant_group_id"]) or {}
                sale_fields = [f for f in (sale_row.get("external_price_fields") or "").split(",") if f]
                item["no_tax_price"] = None
                item["special_invoice_price"] = None
                item["general_invoice_price"] = None
                item["special_invoice_available"] = False
                item["general_invoice_available"] = False
                # 勾了几类就展示几类
                for field in sale_fields:
                    key = price_targets.get(field)
                    if not key:
                        continue
                    item[key] = _plain_price(sale_row.get(RETAIL_PRICE_COLUMNS[field]))
                    if field == "special":
                        item["special_invoice_available"] = item[key] is not None
                    elif field == "general":
                        item["general_invoice_available"] = item[key] is not None
                # 销售价的开票类型及单位、税率，来自该 SKU 的销售价行
                item["invoice_company"] = sale_row.get("retail_invoice_company")
                item["tax_rate"] = sale_row.get("retail_tax_rate")
            result["multiplier"] = "1.00"
        return result
    finally:
        conn.close()


def _merge_variant_prices(main: dict, records: list, part: dict) -> dict:
    """以主记录的元信息为基础，按 external_price_fields 合并各记录的价格。"""
    fields = {f.strip() for f in (main.get("external_price_fields") or "").split(",")}
    # field -> (db_column, response_price_key, response_available_key)
    price_keys = {
        "no_tax": ("no_tax_price", "no_tax_price", None),
        "special": ("purchase_special_invoice", "special_invoice_price", "special_invoice_available"),
        "general": ("purchase_general_invoice", "general_invoice_price", "general_invoice_available"),
    }
    pn, pt = part.get("product_name"), part.get("product_type")
    result = {
        "variant_group_id": main.get("variant_group_id"),
        "specification": main.get("specification"),
        "supplier": main.get("supplier"),
        "is_external_visible": bool(main.get("is_external_visible")),
        "is_discontinued": bool(main.get("is_discontinued")),
        "purchase_shipping": _plain_business_value(main.get("purchase_shipping")),
        "freight_remark": main.get("freight_remark"),
        "shipping_origin": main.get("shipping_origin"),
        "shipping_time": main.get("shipping_time"),
        "warranty_time": main.get("warranty_time"),
        "daily_order_time": main.get("daily_order_time"),
        "quote_time": main.get("quote_time"),
        "expire_date": main.get("expire_date"),
        "quote_remark": main.get("remark"),
        "update_time": main.get("update_time"),
    }
    # 先收集主记录已有的价格
    for field, (db_col, price_key, avail_key) in price_keys.items():
        if field in fields:
            result[price_key] = _scaled_positive_price(main.get(db_col), pn, pt)
            if avail_key is not None:
                result[avail_key] = _is_explicit_zero(main.get(db_col))
        else:
            result[price_key] = None
            if avail_key is not None:
                result[avail_key] = False
    # 从其他记录补充缺失的价格
    for field, (db_col, price_key, avail_key) in price_keys.items():
        if result.get(price_key) is not None:
            continue
        for rec in records:
            rec_fields = {f.strip() for f in (rec.get("external_price_fields") or "").split(",")}
            if field in rec_fields and rec.get(db_col) is not None:
                result[price_key] = _scaled_positive_price(rec.get(db_col), pn, pt)
                if avail_key is not None:
                    result[avail_key] = _is_explicit_zero(rec.get(db_col))
                break
    return result


# 销售主查询
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
    # 2026-11-20 销售主查询不再展示询价记录，OA 询价库查询暂停调用（需要恢复时取消下面注释）
    # inquiry_total = 0
    # inquiry_items = []
    # try:
    #     inquiry_total, inquiry_items = _fetch_inquiry_products(
    #         keyword, sort, candidate_limit
    #     )
    # except Exception as exc:
    #     oa_available = False
    #     logger.warning("[销售查询] OA询价库暂不可用，仅展示配件库 | error=%s", exc)
    inquiry_total = 0
    inquiry_items = []
    oa_available = True

    # 批量获取规格组合数据
    part_ids = [item['id'] for item in parts_items]
    variant_combinations_map = _fetch_variant_combinations(part_ids)
    for item in parts_items:
        item['variant_combinations'] = variant_combinations_map.get(item['id'], [])
    for item in inquiry_items:
        item['variant_combinations'] = []

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
        _record_sales_query(keyword, has_result=(parts_total + inquiry_total > 0))
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


@app.post("/api/sales/inquiry-links")
async def create_sales_inquiry_link(req: SalesInquiryLinkRequest):
    """一键询价成功后立刻记下询价商品与 SPU/SKU 的关联。

    OA 的询价任务此时还没生成，inquiry_mission_id 先留空，
    等 inquiry_sync 拉到任务后按 order_goods_id 回填。
    """
    if req.order_goods_id <= 0:
        raise HTTPException(status_code=400, detail="无效的询价商品 ID")
    part_id = req.part_id if req.part_id and req.part_id > 0 else None
    group_id = str(req.variant_group_id or "").strip() or None
    if part_id is None and group_id is None:
        raise HTTPException(status_code=400, detail="缺少关联的配件或规格")

    conn = get_db()
    try:
        cursor = conn.cursor()
        # matched_by/matched_at 是采购核对时写的，一键询价只建关联，不能顶替核对人
        cursor.execute(
            """INSERT INTO part_inquiries
                   (order_goods_id, part_id, variant_group_id)
               VALUES (%s,%s,%s)
               ON DUPLICATE KEY UPDATE
                   part_id=VALUES(part_id),
                   variant_group_id=VALUES(variant_group_id)""",
            (req.order_goods_id, part_id, group_id),
        )
        conn.commit()
        logger.info(
            "[inquiry-link] 已关联 goods_id=%s part_id=%s sku=%s",
            req.order_goods_id, part_id, group_id,
        )
    except Exception as exc:
        conn.rollback()
        logger.error(
            "[inquiry-link] 回写失败 goods_id=%s part_id=%s sku=%s err=%s",
            req.order_goods_id, part_id, group_id, exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="询价关联保存失败") from exc
    finally:
        conn.close()
    return {"ok": True}


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
