"""询价记录与产品库 SKU 的核对匹配。

询价内容实时读 OA 库，本地 part_inquiries 只保存匹配关系，
不保存规格、价格等快照，避免两边数据不一致。
"""

from collections import defaultdict
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..auth import get_current_user
from ..bootstrap import app, templates
from ..config.constants import PRODUCT_CLASSIFICATION_TREE
from ..model import get_db, get_oa_db
from .inquiries import _fetch_oa_inquiries
from .sales import _oa_image


class MatchSaveRequest(BaseModel):
    inquiry_mission_id: int
    part_id: int
    variant_group_id: Optional[str] = None


def _match_map() -> dict[int, dict]:
    """本地已保存的匹配关系，按询价任务 ID 索引，顺带带上产品信息。"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT qi.inquiry_mission_id, qi.part_id, qi.variant_group_id,
                      qi.matched_by, qi.matched_at,
                      p.product_name AS part_name, p.model AS part_model,
                      p.product_brand AS part_brand, p.product_type AS part_type,
                      (SELECT COUNT(DISTINCT g.variant_group_id)
                         FROM product_variant_group_specs g
                        WHERE g.part_id=qi.part_id) AS part_sku_count
               FROM part_inquiries qi
               LEFT JOIN parts p ON p.id=qi.part_id"""
        )
        return {int(row["inquiry_mission_id"]): row for row in cursor.fetchall()}
    finally:
        conn.close()


@app.get("/inquiry-match", response_class=HTMLResponse)
async def inquiry_match_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="inquiry-match.html",
        context={},
    )


@app.get("/api/inquiry-match/records")
async def list_match_records(
    keyword: str = "",
    status: str = "all",
    page: int = 1,
    page_size: int = 30,
):
    """询价列表。关键词在 OA 侧过滤，匹配状态在本地合并。"""
    rows = _fetch_oa_inquiries(keyword)
    matches = _match_map()

    items = []
    for row in rows:
        mission_id = int(row["inquiry_mission_id"])
        match = matches.get(mission_id) or {}
        items.append({
            "inquiry_mission_id": mission_id,
            "order_goods_id": row.get("order_goods_id"),
            "product_name": row.get("goods_name"),
            "specification": row.get("goods_spec"),
            "product_brand": row.get("factory_name"),
            "image": _oa_image(row.get("images")),
            "purchase_price": row.get("purchase_price"),
            "quote_updated_at": row.get("quote_updated_at"),
            "create_user": row.get("create_user"),
            "create_time": row.get("create_time"),
            "part_id": match.get("part_id"),
            "variant_group_id": match.get("variant_group_id"),
            "matched_by": match.get("matched_by"),
            "matched_part_name": match.get("part_name"),
            "matched_part_model": match.get("part_model"),
            "matched_part_brand": match.get("part_brand"),
            "matched_part_type": match.get("part_type"),
            "matched_part_sku_count": match.get("part_sku_count"),
        })

    pending = [item for item in items if not item["part_id"]]
    matched = [item for item in items if item["part_id"]]
    stats = {"all": len(items), "pending": len(pending), "matched": len(matched)}
    if status == "pending":
        items = pending
    elif status == "matched":
        items = matched

    page = max(1, page)
    page_size = max(1, min(100, page_size))
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    return {
        "items": items[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "stats": stats,
    }


@app.get("/api/inquiry-match/categories")
async def list_match_categories():
    """三级分类树 + 每个三级分类下的产品数。"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT product_type, COUNT(*) AS c FROM parts
               WHERE product_type IS NOT NULL AND product_type<>''
               GROUP BY product_type"""
        )
        counts = {row["product_type"]: int(row["c"]) for row in cursor.fetchall()}
    finally:
        conn.close()

    tree = []
    for first in PRODUCT_CLASSIFICATION_TREE:
        children = []
        for second in first.get("children", []):
            leaves = [
                {"name": name, "count": counts.get(name, 0)}
                for name in second.get("children", [])
            ]
            children.append({"name": second["name"], "children": leaves})
        tree.append({"name": first["name"], "children": children})
    return {"tree": tree, "total": sum(counts.values())}


@app.get("/api/inquiry-match/products")
async def list_match_products(category: str = "", keyword: str = "", limit: int = 500):
    """按三级分类查产品，带 SKU 数和已关联询价数；只给关键词时跨分类搜。"""
    if not category and not keyword:
        return {"items": [], "total": 0, "sku_matched": {}}

    where: list = []
    params: list = []
    if category:
        where.append("p.product_type=%s")
        params.append(category)
    if keyword:
        like = f"%{keyword}%"
        where.append(
            "(p.product_name LIKE %s OR p.model LIKE %s OR p.product_brand LIKE %s)"
        )
        params.extend([like, like, like])

    where_sql = " AND ".join(where) or "1=1"
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) AS c FROM parts p WHERE {where_sql}", params)
        total = int(cursor.fetchone()["c"] or 0)
        cursor.execute(
            f"""SELECT p.id, p.product_name, p.model, p.product_brand,
                      p.product_type, p.update_time_2,
                      (SELECT COUNT(DISTINCT g.variant_group_id)
                         FROM product_variant_group_specs g
                        WHERE g.part_id=p.id) AS sku_count
               FROM parts p
               WHERE {where_sql}
               ORDER BY p.id DESC
               LIMIT {max(1, min(2000, limit))}""",
            params,
        )
        items = list(cursor.fetchall())

        ids = [int(item["id"]) for item in items]
        part_totals: dict[int, int] = defaultdict(int)
        if ids:
            marks = ",".join(["%s"] * len(ids))
            cursor.execute(
                f"""SELECT part_id, COUNT(*) AS c
                    FROM part_inquiries
                    WHERE part_id IN ({marks}) AND variant_group_id IS NOT NULL
                    GROUP BY part_id""",
                ids,
            )
            for row in cursor.fetchall():
                part_totals[int(row["part_id"])] = int(row["c"])
    finally:
        conn.close()

    return {
        "total": total,
        "items": [
            {
                "id": int(item["id"]),
                "product_name": item["product_name"],
                "model": item["model"],
                "product_brand": item["product_brand"],
                "product_type": item["product_type"],
                "update_time": item["update_time_2"],
                "sku_count": int(item["sku_count"]),
                "matched_count": part_totals.get(int(item["id"]), 0),
            }
            for item in items
        ],
    }


@app.post("/api/inquiry-match/save")
async def save_match(req: MatchSaveRequest):
    """保存询价与 SPU/SKU 的匹配关系，按询价任务 ID 幂等。"""
    if not req.part_id:
        raise HTTPException(status_code=400, detail="请先选择产品")

    # 询价记录在 OA 库，本地没有外键，写入前确认任务存在，避免留孤儿匹配
    oa_conn = get_oa_db()
    try:
        oa_cursor = oa_conn.cursor()
        oa_cursor.execute(
            "SELECT 1 FROM yh_query_goods_mission WHERE id=%s LIMIT 1",
            (req.inquiry_mission_id,),
        )
        exists = oa_cursor.fetchone()
    finally:
        oa_conn.close()
    if not exists:
        raise HTTPException(status_code=404, detail="询价记录不存在")

    group_id = (req.variant_group_id or "").strip()
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM parts WHERE id=%s", (req.part_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="产品不存在")

        # variant_group_id 与 parts 之间没有外键，写入前必须校验归属
        if group_id:
            cursor.execute(
                """SELECT 1 FROM product_variant_group_specs
                   WHERE part_id=%s AND variant_group_id=%s LIMIT 1""",
                (req.part_id, group_id),
            )
            if not cursor.fetchone():
                raise HTTPException(status_code=400, detail="该规格组合不属于这个产品")

        user = get_current_user() or {}
        matched_by = (
            user.get("nickname") or user.get("username") or str(user.get("id") or "")
        )
        cursor.execute(
            """INSERT INTO part_inquiries
                   (inquiry_mission_id, part_id, variant_group_id, matched_by, matched_at)
               VALUES (%s,%s,%s,%s,NOW())
               ON DUPLICATE KEY UPDATE
                   part_id=VALUES(part_id),
                   variant_group_id=VALUES(variant_group_id),
                   matched_by=VALUES(matched_by),
                   matched_at=NOW()""",
            (req.inquiry_mission_id, req.part_id, group_id or None, matched_by),
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"message": "已保存"}


@app.get("/api/inquiry-match/detail/{inquiry_mission_id}")
async def inquiry_match_detail(inquiry_mission_id: int):
    """单条询价详情，字段对齐销售页的询价详情弹窗。"""
    conn = get_oa_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT m.id AS inquiry_mission_id, m.order_goods_id, m.quotation_type,
                      m.purchase_price, m.post_fee_purchase, m.post_fee_has_tax_purchase,
                      g.goods_name, g.goods_spec, g.ele_type, g.images,
                      g.goods_price, g.goods_price_tax, g.tax_rate, g.tax_fee,
                      g.post_fee, g.post_fee_tax_rate, g.post_fee_tax_fee,
                      g.post_fee_has_tax, g.goods_num, g.goods_unit, g.total_amount,
                      g.ele_scene, g.inquiry_time, g.create_time,
                      g.goods_describe, g.post_fee_describe, g.remark, g.address,
                      f.factory_name
               FROM yh_query_goods_mission m
               LEFT JOIN yh_query_order_goods g ON g.id=m.order_goods_id
               LEFT JOIN yh_factory f ON f.id=g.factory AND f.delete_time IS NULL
               WHERE m.id=%s""",
            (inquiry_mission_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="询价记录不存在")

    return {
        "inquiry_mission_id": int(row["inquiry_mission_id"]),
        "order_goods_id": row.get("order_goods_id"),
        "product_name": row.get("goods_name"),
        "specification": row.get("goods_spec"),
        "ele_type": row.get("ele_type"),
        "image": _oa_image(row.get("images")),
        "product_brand": row.get("factory_name"),
        "quotation_type": row.get("quotation_type"),
        "purchase_price": row.get("purchase_price"),
        "post_fee_purchase": row.get("post_fee_purchase"),
        "post_fee_has_tax_purchase": row.get("post_fee_has_tax_purchase"),
        "goods_price": row.get("goods_price"),
        "goods_price_tax": row.get("goods_price_tax"),
        "tax_rate": row.get("tax_rate"),
        "tax_fee": row.get("tax_fee"),
        "post_fee": row.get("post_fee"),
        "post_fee_tax_rate": row.get("post_fee_tax_rate"),
        "post_fee_tax_fee": row.get("post_fee_tax_fee"),
        "post_fee_has_tax": row.get("post_fee_has_tax"),
        "goods_num": row.get("goods_num"),
        "goods_unit": row.get("goods_unit"),
        "total_amount": row.get("total_amount"),
        "ele_scene": row.get("ele_scene"),
        "inquiry_time": row.get("inquiry_time"),
        "create_time": row.get("create_time"),
        "goods_describe": row.get("goods_describe"),
        "post_fee_describe": row.get("post_fee_describe"),
        "remark": row.get("remark"),
        "address": row.get("address"),
    }


@app.delete("/api/inquiry-match/{inquiry_mission_id}")
async def clear_match(inquiry_mission_id: int):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM part_inquiries WHERE inquiry_mission_id=%s",
            (inquiry_mission_id,),
        )
        conn.commit()
        deleted = cursor.rowcount
    finally:
        conn.close()
    return {"message": "已清除", "deleted": deleted}
