"""Inquiry listing controls for purchase/admin users."""

from math import ceil
from typing import Optional

import pymysql
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..auth import get_current_user_id
from ..bootstrap import app, templates
from ..feedback import FEEDBACK_TYPE_LABELS
from ..shared import get_db, logger
from .sales import _oa_connection, _oa_image


class InquiryListingRequest(BaseModel):
    listing_status: int
    inquiry_goods_id: Optional[int] = None
    feedback_id: Optional[int] = None
    reason: Optional[str] = None


def _safe_local_query(sql: str, params=()):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return cursor.fetchall()
    except pymysql.err.ProgrammingError as exc:
        if exc.args and exc.args[0] in {1054, 1146}:
            logger.warning("[询价管理] 本地表结构未初始化 | error=%s", exc)
            return []
        raise
    finally:
        conn.close()


def _listing_status_map() -> dict[int, dict]:
    rows = _safe_local_query(
        """SELECT inquiry_mission_id, inquiry_goods_id, listing_status,
                  feedback_id, reason, updated_by, created_at, updated_at
           FROM sales_inquiry_listing_status"""
    )
    return {int(row["inquiry_mission_id"]): row for row in rows}


def _feedback_map() -> dict[int, dict]:
    rows = _safe_local_query(
        """SELECT feedback.id, feedback.inquiry_mission_id,
                  feedback.inquiry_goods_id, feedback.feedback_user_id,
                  feedback.issue_types, feedback.description, feedback.status,
                  feedback.handled_by, feedback.handled_at,
                  feedback.created_at, feedback.updated_at,
                  COALESCE(NULLIF(reporter.nickname,''), reporter.username,
                           CONCAT('用户', feedback.feedback_user_id), '未知用户')
                      AS feedback_user_name,
                  COALESCE(NULLIF(handler.nickname,''), handler.username,
                           CONCAT('用户', feedback.handled_by), '')
                      AS handled_by_name
           FROM sales_product_feedback feedback
           LEFT JOIN yh_admin_user reporter ON reporter.id=feedback.feedback_user_id
           LEFT JOIN yh_admin_user handler ON handler.id=feedback.handled_by
           WHERE feedback.source_type='inquiry'
             AND feedback.inquiry_mission_id IS NOT NULL
           ORDER BY CASE feedback.status WHEN 'pending' THEN 0 ELSE 1 END,
                    feedback.created_at DESC, feedback.id DESC"""
    )
    grouped = {}
    for row in rows:
        mission_id = int(row["inquiry_mission_id"])
        codes = [
            item.strip()
            for item in str(row.get("issue_types") or "").split(",")
            if item.strip()
        ]
        row["issue_type_labels"] = [
            FEEDBACK_TYPE_LABELS.get(code, code)
            for code in codes
        ]
        group = grouped.setdefault(
            mission_id,
            {"latest": row, "pending_count": 0, "total_count": 0},
        )
        group["total_count"] += 1
        if row.get("status") == "pending":
            group["pending_count"] += 1
    return grouped


def _fetch_oa_inquiries(keyword: str) -> list[dict]:
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
    conn = _oa_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""SELECT m.id AS inquiry_mission_id, m.order_goods_id,
                       m.quotation_type, m.purchase_price,
                       m.post_fee_purchase, m.post_fee_has_tax_purchase,
                       COALESCE(m.renew_time, m.update_time, m.finish_time,
                                m.create_time, g.quote_time, g.update_time,
                                g.inquiry_time, g.create_time) AS quote_updated_at,
                       g.goods_name, g.ele_type, g.goods_spec, g.images,
                       f.factory_name
                FROM yh_query_goods_mission m
                LEFT JOIN yh_query_order_goods g ON g.id=m.order_goods_id
                LEFT JOIN yh_factory f ON f.id=g.factory AND f.delete_time IS NULL
                WHERE {" AND ".join(where)}
                ORDER BY quote_updated_at DESC, m.id DESC
                LIMIT 6000""",
            params,
        )
        return cursor.fetchall()
    finally:
        conn.close()


def _decorate_inquiries(rows: list[dict]) -> list[dict]:
    statuses = _listing_status_map()
    feedback = _feedback_map()
    items = []
    for row in rows:
        mission_id = int(row["inquiry_mission_id"])
        status = statuses.get(mission_id) or {}
        feedback_group = feedback.get(mission_id) or {
            "latest": None,
            "pending_count": 0,
            "total_count": 0,
        }
        latest_feedback = feedback_group.get("latest")
        items.append({
            "inquiry_mission_id": mission_id,
            "inquiry_goods_id": row.get("order_goods_id"),
            "product_name": row.get("goods_name"),
            "model": row.get("ele_type"),
            "specification": row.get("goods_spec"),
            "product_brand": row.get("factory_name"),
            "image": _oa_image(row.get("images")),
            "quotation_type": row.get("quotation_type"),
            "purchase_price": row.get("purchase_price"),
            "post_fee_purchase": row.get("post_fee_purchase"),
            "post_fee_has_tax_purchase": row.get("post_fee_has_tax_purchase"),
            "quote_updated_at": row.get("quote_updated_at"),
            "listing_status": int(status.get("listing_status", 1) or 0),
            "listing_reason": status.get("reason"),
            "listing_updated_at": status.get("updated_at"),
            "feedback": latest_feedback,
            "pending_feedback_count": feedback_group.get("pending_count", 0),
            "feedback_count": feedback_group.get("total_count", 0),
        })
    return items


@app.get("/inquiries", response_class=HTMLResponse)
async def inquiry_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="inquiries.html",
        context={},
    )


@app.get("/api/inquiries")
async def list_inquiries(
    keyword: str = "",
    status: str = "pending",
    page: int = 1,
    page_size: int = 20,
):
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    status = status.strip().lower() or "pending"
    if status not in {"pending", "listed", "hidden", "all"}:
        raise HTTPException(status_code=400, detail="无效的询价状态")
    try:
        items = _decorate_inquiries(_fetch_oa_inquiries(keyword.strip()[:100]))
    except Exception as exc:
        logger.exception("[询价管理] 列表加载失败 | error=%s", exc)
        raise HTTPException(status_code=503, detail="询价记录暂时无法读取") from exc

    stats = {
        "all": len(items),
        "pending": sum(1 for item in items if item["pending_feedback_count"] > 0),
        "listed": sum(1 for item in items if item["listing_status"] == 1),
        "hidden": sum(1 for item in items if item["listing_status"] == 0),
    }
    if status == "pending":
        items = [item for item in items if item["pending_feedback_count"] > 0]
    elif status == "listed":
        items = [item for item in items if item["listing_status"] == 1]
    elif status == "hidden":
        items = [item for item in items if item["listing_status"] == 0]

    total = len(items)
    pages = max(1, ceil(total / page_size))
    page = min(page, pages)
    offset = (page - 1) * page_size
    return {
        "items": items[offset:offset + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "stats": stats,
    }


@app.patch("/api/inquiries/{inquiry_mission_id}/listing-status")
async def update_inquiry_listing_status(
    inquiry_mission_id: int,
    req: InquiryListingRequest,
):
    if inquiry_mission_id <= 0:
        raise HTTPException(status_code=400, detail="无效的询价任务ID")
    listing_status = 1 if int(req.listing_status or 0) == 1 else 0
    reason = str(req.reason or "").strip()[:500] or None
    operator_id = get_current_user_id()
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO sales_inquiry_listing_status
                   (inquiry_mission_id, inquiry_goods_id, listing_status,
                    feedback_id, reason, updated_by)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE
                   inquiry_goods_id=COALESCE(VALUES(inquiry_goods_id), inquiry_goods_id),
                   listing_status=VALUES(listing_status),
                   feedback_id=VALUES(feedback_id),
                   reason=VALUES(reason),
                   updated_by=VALUES(updated_by),
                   updated_at=NOW()""",
            (
                inquiry_mission_id,
                req.inquiry_goods_id,
                listing_status,
                req.feedback_id,
                reason,
                operator_id,
            ),
        )
        if listing_status == 0 and req.feedback_id:
            cursor.execute(
                """UPDATE sales_product_feedback
                   SET status='completed', handled_by=%s,
                       handled_at=COALESCE(handled_at, NOW()),
                       handle_remark=COALESCE(%s, handle_remark)
                   WHERE id=%s AND source_type='inquiry'""",
                (operator_id, reason, req.feedback_id),
            )
        conn.commit()
        return {
            "message": "已恢复上架" if listing_status == 1 else "已下架询价记录",
            "listing_status": listing_status,
        }
    except pymysql.err.ProgrammingError as exc:
        conn.rollback()
        if exc.args and exc.args[0] in {1054, 1146}:
            raise HTTPException(status_code=503, detail="请先执行询价上下架SQL脚本") from exc
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
