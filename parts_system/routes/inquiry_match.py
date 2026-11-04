"""询价记录与产品库 SKU 的核对匹配。

询价内容实时读 OA 库，本地 part_inquiries 只保存匹配关系，
不保存规格、价格等快照，避免两边数据不一致。
"""

from collections import defaultdict
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..audit import write_operation_log
from ..auth import get_current_user
from ..bootstrap import app, templates
from ..config.constants import PRODUCT_CLASSIFICATION_TREE
from ..model import get_db, get_oa_db
from ..util import parse_image_urls
from .inquiries import _fetch_oa_inquiries
from .sales import _oa_image


class MatchSaveRequest(BaseModel):
    inquiry_mission_id: int
    part_id: int
    variant_group_id: Optional[str] = None


class BatchMatchSaveRequest(BaseModel):
    inquiry_mission_ids: list[int]
    part_id: int
    variant_group_id: Optional[str] = None


# 单次批量上限：一个型号组的量级通常几十条，500 足够，再多基本是选错了
BATCH_LIMIT = 500


def _load_inquiry_brief(inquiry_mission_id: int):
    """从 OA 读取询价商品名和型号；记录不存在返回 None。"""
    conn = get_oa_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT g.goods_name, g.goods_spec, g.ele_type
               FROM yh_query_goods_mission m
               LEFT JOIN yh_query_order_goods g ON g.id=m.order_goods_id
               WHERE m.id=%s LIMIT 1""",
            (inquiry_mission_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    # OA 的型号基本填在 goods_spec 里，ele_type 只有测试数据在用
    return (
        str(row.get("goods_name") or "").strip(),
        str(row.get("goods_spec") or row.get("ele_type") or "").strip(),
    )


def _inquiry_label(goods_name, inquiry_model) -> str:
    """日志摘要里的商品标识，如（外呼显示板 MCTC-HCB-D631S-NTSY）。"""
    title = " ".join(x for x in (goods_name, inquiry_model) if x)
    return f"（{title}）" if title else ""


def _group_spec_text(cursor, part_id, group_id) -> str:
    """规格组合的可读文本，如 载重=1000kg/速度=1.0m/s。"""
    if not part_id or not group_id:
        return ""
    cursor.execute(
        """SELECT GROUP_CONCAT(CONCAT(s.spec_name,'=',s.spec_value)
                                ORDER BY l.sort_order, l.id SEPARATOR '/') AS text
           FROM product_variant_group_specs l
           JOIN product_variant_specs s ON s.id=l.spec_id
           WHERE l.part_id=%s AND l.variant_group_id=%s""",
        (part_id, group_id),
    )
    row = cursor.fetchone()
    return (row or {}).get("text") or ""


def _log_match_change(
    cursor,
    *,
    user_id,
    goods_name: str,
    inquiry_model: str,
    previous,
    part_id: int,
    group_id: str,
):
    """关联变更写日志：换产品时旧产品记取消、新产品记关联，值没变不写。"""
    old_part_id = int(previous["part_id"]) if previous and previous.get("part_id") else None
    old_group_id = (previous.get("variant_group_id") or "") if previous else ""
    new_group_id = group_id or ""
    if previous and old_part_id == part_id and old_group_id == new_group_id:
        return

    # 摘要只写商品名称和型号，不带询价记录 ID
    label = _inquiry_label(goods_name, inquiry_model)
    new_spec = _group_spec_text(cursor, part_id, new_group_id)

    if old_part_id and old_part_id != part_id:
        old_spec = _group_spec_text(cursor, old_part_id, old_group_id)
        write_operation_log(
            cursor,
            part_id=old_part_id,
            operation_type="INQUIRY",
            module_code="INQUIRY",
            user_id=user_id,
            detail=f"取消关联询价{label}"
            + (f"，规格 {old_spec}" if old_spec else ""),
        )

    if old_part_id == part_id and old_group_id and new_group_id and old_group_id != new_group_id:
        old_spec = _group_spec_text(cursor, part_id, old_group_id) or old_group_id
        detail = (
            f"关联询价{label}"
            f"，规格 {old_spec} → {new_spec or new_group_id}"
        )
    else:
        detail = f"关联询价{label}" + (
            f"，规格 {new_spec}" if new_spec else ""
        )

    write_operation_log(
        cursor,
        part_id=part_id,
        operation_type="INQUIRY",
        module_code="INQUIRY",
        user_id=user_id,
        detail=detail,
    )


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


def _to_amount(value) -> float:
    """OA 里价格字段有 decimal 也有 varchar，统一转成数字，转不动当 0。"""
    try:
        return float(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _fetch_page_quotes(items: list[dict]) -> dict:
    """按 (询价单, 商品) 取明细报价，只查当前页用到的键。"""
    keys = sorted({
        (int(item["query_order_id"]), int(item["order_goods_id"]))
        for item in items
        if item.get("query_order_id") and item.get("order_goods_id")
    })
    if not keys:
        return {}
    clause = " OR ".join(["(query_order_id=%s AND order_goods_id=%s)"] * len(keys))
    params = [value for key in keys for value in key]
    conn = get_oa_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""SELECT d.query_order_id, d.order_goods_id, d.is_selected,
                       d.purchase_quotation_type, d.jh_goods_price, d.jh_goods_price_has_tax,
                       d.supplier_name, d.purchase_source, d.goods_spec, d.warehouse,
                       d.reminder, d.profit_rate, d.jh_post_fee, d.purchase_price,
                       f.factory_name, b.brand_name AS ele_brand_name
                  FROM yh_query_goods_mission_detail d
                  LEFT JOIN yh_factory f ON f.id=d.factory AND f.delete_time IS NULL
                  LEFT JOIN yh_ele_brand b ON b.id=d.ele_brand AND b.delete_time IS NULL
                 WHERE ({clause}) AND d.delete_time IS NULL
                 ORDER BY d.is_selected DESC, d.id DESC""",
            params,
        )
        grouped = defaultdict(list)
        for row in cursor.fetchall():
            key = (int(row["query_order_id"]), int(row["order_goods_id"]))
            grouped[key].append(row)
        return grouped
    finally:
        conn.close()


def _pick_fee_amount(quote_value, goods_value) -> str:
    """运费和商品单价一样：报价为空时回落到商品上的运费。"""
    if _to_amount(quote_value) > 0:
        return str(quote_value).strip()
    if _to_amount(goods_value) > 0:
        return str(goods_value).strip()
    return ""


def _pick_purchase_price(quotes: list[dict], item: dict) -> tuple[str, str]:
    """明细优先，商品表兜底，返回 (单价, 标签)。类型字段填反时看另一侧。"""
    candidates = []
    if quotes:
        top = quotes[0]
        candidates.append((
            str(top.get("purchase_quotation_type") or "").strip(),
            top.get("jh_goods_price"),
            top.get("jh_goods_price_has_tax"),
        ))
    candidates.append((
        str(item.get("goods_quotation_type") or "").strip(),
        item.get("jh_goods_price"),
        item.get("jh_goods_price_has_tax"),
    ))
    for quote_type, no_tax, with_tax in candidates:
        if quote_type == "1":
            ordered = ((with_tax, "含税采购价"), (no_tax, "无税采购价"))
        else:
            ordered = ((no_tax, "无税采购价"), (with_tax, "含税采购价"))
        for value, label in ordered:
            if _to_amount(value) > 0:
                return str(value).strip(), label
    return "", ""


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
            "query_order_id": row.get("query_order_id"),
            "product_name": row.get("goods_name"),
            "specification": row.get("goods_spec"),
            "product_brand": row.get("factory_name"),
            "image": _oa_image(row.get("images")),
            "images": parse_image_urls(row.get("images")),
            "purchase_price": row.get("purchase_price"),
            "goods_quotation_type": row.get("goods_quotation_type"),
            "jh_goods_price": row.get("jh_goods_price"),
            "jh_goods_price_has_tax": row.get("jh_goods_price_has_tax"),
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
    page_items = items[start:start + page_size]
    # 只给当前页查明细报价，避免为一页数据把全量询价都连一遍
    quotes_map = _fetch_page_quotes(page_items)
    for item in page_items:
        quotes = quotes_map.get(
            (item["query_order_id"], item["order_goods_id"]), []
        )
        price, label = _pick_purchase_price(quotes, item)
        item["purchase_price"] = price
        item["price_label"] = label
        # 取价用完就丢，这几个字段前端用不到
        for key in ("query_order_id", "goods_quotation_type",
                    "jh_goods_price", "jh_goods_price_has_tax"):
            item.pop(key, None)
    return {
        "items": page_items,
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
async def list_match_products(category: str = "", keyword: str = "", page: int = 1, page_size: int = 30):
    """产品列表：默认展示全部产品，可选分类过滤或关键词跨分类搜，分页返回。"""
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
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size
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
               LIMIT %s OFFSET %s""",
            [*params, page_size, offset],
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
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
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
    brief = _load_inquiry_brief(req.inquiry_mission_id)
    if not brief:
        raise HTTPException(status_code=404, detail="询价记录不存在")
    goods_name, inquiry_model = brief

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
            "SELECT part_id, variant_group_id FROM part_inquiries "
            "WHERE inquiry_mission_id=%s",
            (req.inquiry_mission_id,),
        )
        previous = cursor.fetchone()

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
        _log_match_change(
            cursor,
            user_id=user.get("id"),
            goods_name=goods_name,
            inquiry_model=inquiry_model,
            previous=previous,
            part_id=req.part_id,
            group_id=group_id,
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"message": "已保存"}


@app.get("/api/inquiry-match/batch/preview")
async def batch_preview(keyword: str = "", status: str = "all"):
    """批量关联用：当前搜索下每条询价的 id、规格型号和已关联产品。

    规格型号是分组依据，同一规格套同一个 SKU 才安全；
    没搜索词时没必要把 7000 条都吐给前端，直接让页面走手工勾选。
    """
    keyword = keyword.strip()
    if not keyword:
        return {"items": [], "total": 0, "hint": "先搜索型号再按组批量选择"}
    matches = _match_map()
    items = []
    for row in _fetch_oa_inquiries(keyword):
        mission_id = int(row["inquiry_mission_id"])
        matched = matches.get(mission_id) or {}
        row_status = "matched" if matched.get("part_id") else "pending"
        if status in ("pending", "matched") and row_status != status:
            continue
        items.append({
            "id": mission_id,
            "spec": str(row.get("goods_spec") or "").strip(),
            "name": row.get("goods_name") or "",
            "matched_part_id": matched.get("part_id"),
            "matched_part_name": matched.get("part_name"),
        })
    return {"items": items, "total": len(items)}


@app.post("/api/inquiry-match/batch/save")
async def batch_save_match(req: BatchMatchSaveRequest):
    """把同一规格的一批询价关联到同一个产品与 SKU，整批一个事务。"""
    if not req.part_id:
        raise HTTPException(status_code=400, detail="请先选择产品")
    mission_ids = list(dict.fromkeys(int(item) for item in req.inquiry_mission_ids))
    if not mission_ids:
        raise HTTPException(status_code=400, detail="请先勾选询价记录")
    if len(mission_ids) > BATCH_LIMIT:
        raise HTTPException(
            status_code=400, detail=f"单次最多关联 {BATCH_LIMIT} 条，请按型号分批"
        )
    group_id = (req.variant_group_id or "").strip()

    # 询价在 OA 库：一次 IN 查存在性，顺带取规格。跨规格整批套同一个 SKU 必然是误操作
    oa_conn = get_oa_db()
    try:
        oa_cursor = oa_conn.cursor()
        placeholders = ",".join(["%s"] * len(mission_ids))
        oa_cursor.execute(
            f"""SELECT m.id, g.goods_spec
                  FROM yh_query_goods_mission m
                  LEFT JOIN yh_query_order_goods g ON g.id=m.order_goods_id
                 WHERE m.id IN ({placeholders})""",
            mission_ids,
        )
        rows = oa_cursor.fetchall()
    finally:
        oa_conn.close()
    found = {int(row["id"]) for row in rows}
    missing = [mid for mid in mission_ids if mid not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"{len(missing)} 条询价记录不存在")
    specs = {str(row.get("goods_spec") or "").strip() for row in rows}
    if len(specs) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"选中包含 {len(specs)} 种规格型号，请按规格分组后分别关联",
        )
    spec_text = next(iter(specs), "") or "无规格"
    # 空规格之间无法证明是同一个东西，多条套一个 SKU 必然写错，只允许单条走原有流程
    if not spec_text.strip() or spec_text == "无规格":
        if len(mission_ids) > 1:
            raise HTTPException(
                status_code=400,
                detail="无规格型号的记录不支持批量关联，请逐条关联",
            )

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM parts WHERE id=%s", (req.part_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="产品不存在")
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
        placeholders = ",".join(["%s"] * len(mission_ids))
        cursor.execute(
            f"""SELECT inquiry_mission_id, part_id FROM part_inquiries
                 WHERE inquiry_mission_id IN ({placeholders})""",
            mission_ids,
        )
        previous = {int(row["inquiry_mission_id"]): row.get("part_id")
                    for row in cursor.fetchall()}
        overwritten = sum(
            1 for part in previous.values() if part and int(part) != req.part_id
        )

        cursor.executemany(
            """INSERT INTO part_inquiries
                   (inquiry_mission_id, part_id, variant_group_id, matched_by, matched_at)
               VALUES (%s,%s,%s,%s,NOW())
               ON DUPLICATE KEY UPDATE
                   part_id=VALUES(part_id),
                   variant_group_id=VALUES(variant_group_id),
                   matched_by=VALUES(matched_by),
                   matched_at=NOW()""",
            [(mid, req.part_id, group_id or None, matched_by) for mid in mission_ids],
        )
        detail = f"批量关联 {len(mission_ids)} 条询价（规格 {spec_text}）"
        if overwritten:
            detail += f"，覆盖原关联 {overwritten} 条"
        write_operation_log(
            cursor,
            part_id=req.part_id,
            operation_type="INQUIRY",
            module_code="INQUIRY",
            user_id=user.get("id"),
            detail=detail,
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"saved": len(mission_ids), "overwritten": overwritten}


@app.get("/api/inquiry-match/detail/{inquiry_mission_id}")
async def inquiry_match_detail(inquiry_mission_id: int):
    """单条询价详情，字段对齐销售页的询价详情弹窗。"""
    conn = get_oa_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT m.id AS inquiry_mission_id, m.order_goods_id, m.query_order_id,
                     m.mission_sn, m.mission_type, m.mission_status, m.used_time,
                     COALESCE(NULLIF(TRIM(a.nickname), ''), a.username) AS creator_name,
                     m.quotation_type, m.purchase_price,
                     m.post_fee_purchase, m.post_fee_has_tax_purchase,
                     g.quotation_type AS goods_quotation_type,
                     g.jh_goods_price, g.jh_goods_price_has_tax,
                     g.invoice, g.goods_name, g.goods_spec, g.ele_type, g.images,
                      g.goods_price, g.goods_price_tax, g.tax_rate, g.tax_fee,
                      g.post_fee, g.post_fee_tax_rate, g.post_fee_tax_fee,
                      g.post_fee_has_tax, g.goods_num, g.goods_unit, g.total_amount,
                      g.ele_scene, g.inquiry_time, g.create_time,
                      g.goods_describe, g.post_fee_describe, g.remark, g.address,
                      f.factory_name
               FROM yh_query_goods_mission m
               LEFT JOIN yh_admin_user a ON a.id=m.admin_id
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

    # 和列表同一套取价规则，保证两边显示一致
    quote_key = None
    if row.get("query_order_id") and row.get("order_goods_id"):
        quote_key = (int(row["query_order_id"]), int(row["order_goods_id"]))
    quotes_map = _fetch_page_quotes([{
        "query_order_id": row.get("query_order_id"),
        "order_goods_id": row.get("order_goods_id"),
    }])
    price, price_label = _pick_purchase_price(
        quotes_map.get(quote_key, []) if quote_key else [], row
    )
    quotes = [
        {
            "index": index,
            "supplier_name": quote.get("supplier_name"),
            "purchase_source": quote.get("purchase_source"),
            "factory_name": quote.get("factory_name"),
            "ele_brand_name": quote.get("ele_brand_name"),
            "goods_spec": quote.get("goods_spec"),
            "warehouse": quote.get("warehouse"),
            "reminder": quote.get("reminder"),
            "purchase_quotation_type": quote.get("purchase_quotation_type"),
            "jh_goods_price": quote.get("jh_goods_price"),
            "jh_goods_price_has_tax": quote.get("jh_goods_price_has_tax"),
            "profit_rate": quote.get("profit_rate"),
            "jh_post_fee": quote.get("jh_post_fee"),
            "purchase_price": quote.get("purchase_price"),
            "is_selected": quote.get("is_selected"),
        }
        for index, quote in enumerate(quotes_map.get(quote_key, []) if quote_key else [], start=1)
    ]

    used_seconds = int(row.get("used_time") or 0)
    mission_time_text = ""
    if used_seconds > 0:
        hours, rest = divmod(used_seconds, 3600)
        minutes, seconds = divmod(rest, 60)
        parts = []
        if hours:
            parts.append(f"{hours}小时")
        if minutes:
            parts.append(f"{minutes}分")
        parts.append(f"{seconds}秒")
        mission_time_text = "".join(parts)

    return {
        "inquiry_mission_id": int(row["inquiry_mission_id"]),
        "mission_sn": row.get("mission_sn"),
        "mission_type": row.get("mission_type"),
        "mission_status_text": "已完成" if int(row.get("mission_status") or 0) == 4 else "",
        "mission_time_text": mission_time_text,
        "creator": row.get("creator_name"),
        "invoice": row.get("invoice"),
        "quotes": quotes,
        "order_goods_id": row.get("order_goods_id"),
        "product_name": row.get("goods_name"),
        "specification": row.get("goods_spec"),
        "ele_type": row.get("ele_type"),
        "image": _oa_image(row.get("images")),
        "images": parse_image_urls(row.get("images")),
        "product_brand": row.get("factory_name"),
        "quotation_type": row.get("quotation_type"),
        "purchase_price": price,
        "price_label": price_label,
        "post_fee_purchase": _pick_fee_amount(
            row.get("post_fee_purchase"), row.get("post_fee")
        ),
        "post_fee_has_tax_purchase": _pick_fee_amount(
            row.get("post_fee_has_tax_purchase"), row.get("post_fee_has_tax")
        ),
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
    goods_name, inquiry_model = _load_inquiry_brief(inquiry_mission_id) or ("", "")
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT part_id, variant_group_id FROM part_inquiries "
            "WHERE inquiry_mission_id=%s",
            (inquiry_mission_id,),
        )
        previous = cursor.fetchone()
        cursor.execute(
            "DELETE FROM part_inquiries WHERE inquiry_mission_id=%s",
            (inquiry_mission_id,),
        )
        deleted = cursor.rowcount
        if previous and previous.get("part_id"):
            part_id = int(previous["part_id"])
            spec_text = _group_spec_text(
                cursor, part_id, previous.get("variant_group_id")
            )
            write_operation_log(
                cursor,
                part_id=part_id,
                operation_type="INQUIRY",
                module_code="INQUIRY",
                detail=f"取消关联询价{_inquiry_label(goods_name, inquiry_model)}"
                + (f"，规格 {spec_text}" if spec_text else ""),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"message": "已清除", "deleted": deleted}
