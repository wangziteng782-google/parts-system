"""Goods 待改正反馈查询与处理接口。"""

from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel

from ..auth import get_current_user_id
from ..audit import write_operation_log
from ..bootstrap import app
from ..feedback import (
    FEEDBACK_STATUSES,
    FEEDBACK_TYPE_LABELS,
)
from ..model import get_db
from ..config import logger


class FeedbackStatusRequest(BaseModel):
    status: str
    handle_remark: Optional[str] = None


def _decorate_feedback(row: dict) -> dict:
    codes = [item.strip() for item in str(row.get("issue_types") or "").split(",") if item.strip()]
    row["issue_type_codes"] = codes
    row["issue_type_labels"] = [FEEDBACK_TYPE_LABELS.get(code, code) for code in codes]
    return row


@app.get("/api/feedback/pending-count")
async def pending_feedback_count():
    """返回待改正产品数量和待处理反馈数量。"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT COUNT(*) AS feedback_count,
                      COUNT(DISTINCT parts_id) AS product_count
               FROM sales_product_feedback
               WHERE status='pending' AND parts_id IS NOT NULL"""
        )
        return cursor.fetchone()
    finally:
        conn.close()


@app.get("/api/products/{product_id}/feedback")
async def list_product_feedback(product_id: int, status: Optional[str] = None):
    """按产品读取反馈，默认返回全部状态。"""
    if product_id <= 0:
        raise HTTPException(status_code=400, detail="无效的产品ID")
    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail="无效的反馈状态")
    conn = get_db()
    try:
        cursor = conn.cursor()
        params = [product_id]
        status_sql = ""
        if normalized_status:
            status_sql = " AND feedback.status=%s"
            params.append(normalized_status)
        cursor.execute(
            f"""SELECT feedback.id, feedback.parts_id, feedback.inquiry_goods_id,
                       feedback.feedback_user_id, feedback.source_type,
                       feedback.issue_types, feedback.description, feedback.status,
                       feedback.handled_by, feedback.handled_at,
                       feedback.handle_remark, feedback.created_at, feedback.updated_at,
                       COALESCE(NULLIF(reporter.nickname,''), reporter.username,
                                CONCAT('用户', feedback.feedback_user_id), '未知用户') AS feedback_user_name,
                       COALESCE(NULLIF(handler.nickname,''), handler.username,
                                CONCAT('用户', feedback.handled_by), '') AS handled_by_name
                FROM sales_product_feedback feedback
                LEFT JOIN yh_admin_user reporter ON reporter.id=feedback.feedback_user_id
                LEFT JOIN yh_admin_user handler ON handler.id=feedback.handled_by
                WHERE feedback.parts_id=%s{status_sql}
                ORDER BY CASE feedback.status WHEN 'pending' THEN 0 ELSE 1 END,
                         feedback.created_at DESC, feedback.id DESC""",
            params,
        )
        return [_decorate_feedback(row) for row in cursor.fetchall()]
    finally:
        conn.close()


@app.patch("/api/feedback/{feedback_id}/status")
async def update_feedback_status(feedback_id: int, req: FeedbackStatusRequest):
    """将反馈标记为已完成、已忽略，或重新设为待处理。"""
    status = str(req.status or "").strip().lower()
    if status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail="反馈状态只能是待处理、已完成或已忽略")
    remark = str(req.handle_remark or "").strip()[:500] or None
    handler_id = get_current_user_id()
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, parts_id, status FROM sales_product_feedback WHERE id=%s FOR UPDATE",
            (feedback_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="反馈记录不存在")
        if status == "pending":
            cursor.execute(
                """UPDATE sales_product_feedback
                   SET status='pending', handled_by=NULL, handled_at=NULL, handle_remark=%s
                   WHERE id=%s""",
                (remark, feedback_id),
            )
        else:
            cursor.execute(
                """UPDATE sales_product_feedback
                   SET status=%s, handled_by=%s, handled_at=NOW(), handle_remark=%s
                   WHERE id=%s""",
                (status, handler_id, remark, feedback_id),
            )
        if (
            status == "completed"
            and row.get("status") != "completed"
            and row.get("parts_id") is not None
        ):
            cursor.execute(
                """SELECT COUNT(*) AS pending_count
                   FROM sales_product_feedback
                   WHERE parts_id=%s AND status='pending'""",
                (row["parts_id"],),
            )
            if int(cursor.fetchone().get("pending_count") or 0) == 0:
                write_operation_log(
                    cursor,
                    part_id=row["parts_id"],
                    operation_type="CORRECTED",
                    module_code="WORKFLOW",
                    detail="销售反馈问题已全部改正",
                    user_id=handler_id,
                )
        conn.commit()
        logger.info(
            "[反馈处理] feedback_id=%s | parts_id=%s | %s -> %s | handler=%s",
            feedback_id,
            row.get("parts_id"),
            row.get("status"),
            status,
            handler_id,
        )
        return {"message": "反馈状态已更新", "status": status}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
