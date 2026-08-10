from datetime import date
from typing import Optional

from fastapi import HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from ..auth import get_current_user_id
from ..bootstrap import app, templates
from ..shared import (
    IMAGE_FIELDS,
    ensure_employee_operation_logs_table,
    get_db,
    parse_image_urls,
)


OPERATION_LABELS = {
    "CREATE": "新增",
    "UPDATE": "修改",
    "DELETE": "删除",
    "COMPLETE": "已修改",
    "CORRECTED": "已改正",
}

MODULE_LABELS = {
    "PRODUCT": "产品信息",
    "SPEC": "规格配置",
    "PRICE": "供应商价格",
    "IMAGE": "图片资料",
    "CLASSIFICATION": "产品分类",
    "WORKFLOW": "完成标记",
}

PRODUCT_NAME_SQL = (
    "COALESCE(NULLIF(TRIM(l.product_name_snapshot), ''), "
    "NULLIF(TRIM(p.product_name), ''), "
    "CONCAT('配件 #', COALESCE(l.part_id, '-')))"
)
MODEL_SQL = (
    "COALESCE(NULLIF(TRIM(l.model_snapshot), ''), "
    "NULLIF(TRIM(p.model), ''), '')"
)

def _normalize_operation(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip().upper()
    if normalized not in OPERATION_LABELS:
        raise HTTPException(status_code=400, detail="不支持的操作类型")
    return normalized


def _build_where(
    keyword: Optional[str],
    user_id: Optional[int],
    module_code: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
    operation_type: Optional[str] = None,
):
    clauses = ["1=1"]
    params = []

    if keyword and keyword.strip():
        value = f"%{keyword.strip()}%"
        clauses.append(
            """
            (
                l.product_name_snapshot LIKE %s OR l.model_snapshot LIKE %s
                OR p.product_name LIKE %s OR p.model LIKE %s OR p.sku_code LIKE %s
                OR p.product_brand LIKE %s OR l.detail LIKE %s
                OR u.nickname LIKE %s OR u.username LIKE %s
            )
            """
        )
        params.extend([value] * 9)
    if user_id is not None:
        clauses.append("l.user_id = %s")
        params.append(user_id)
    if module_code:
        clauses.append("l.module_code = %s")
        params.append(module_code.strip().upper())
    if start_date:
        clauses.append("l.created_at >= %s")
        params.append(start_date)
    if end_date:
        clauses.append("l.created_at < DATE_ADD(%s, INTERVAL 1 DAY)")
        params.append(end_date)
    if operation_type:
        clauses.append("l.operation_type = %s")
        params.append(operation_type)

    return " AND ".join(clauses), params


def _serialize_log(row):
    image_url = ""
    for field in IMAGE_FIELDS:
        urls = parse_image_urls(row.pop(field, None))
        if urls:
            image_url = urls[0]
            break

    operation_type = (row.get("operation_type") or "").upper()
    module_code = (row.get("module_code") or "PRODUCT").upper()
    row["operation_type"] = operation_type
    row["operation_label"] = OPERATION_LABELS.get(
        operation_type, operation_type or "未知"
    )
    row["module_code"] = module_code
    row["module_label"] = MODULE_LABELS.get(module_code, module_code)
    row["image_url"] = image_url
    row["operator_name"] = (
        row.get("nickname")
        or row.get("username")
        or f"用户#{row.get('user_id')}"
    )
    return row


def _split_codes(value):
    return [item.strip().upper() for item in str(value or "").split(",") if item.strip()]


def _serialize_log_group(row):
    row = _serialize_log(row)
    operation_types = _split_codes(row.pop("operation_types", ""))
    module_codes = _split_codes(row.pop("module_codes", ""))
    row["operation_types"] = operation_types
    row["operation_labels"] = [
        OPERATION_LABELS.get(code, code) for code in operation_types
    ]
    row["module_codes"] = module_codes
    row["module_labels"] = [MODULE_LABELS.get(code, code) for code in module_codes]
    row["log_count"] = int(row.get("log_count") or 0)
    return row


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={},
    )


@app.get("/api/logs/users")
async def list_log_users():
    conn = get_db()
    try:
        ensure_employee_operation_logs_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, nickname, avatar, role_id, department_id
            FROM yh_admin_user
            WHERE role_id IN (4, 36, 37)
            ORDER BY COALESCE(NULLIF(nickname, ''), username), id
            """
        )
        rows = cursor.fetchall()
        return {
            "current_user_id": get_current_user_id(),
            "items": [
                {
                    "id": row["id"],
                    "username": row.get("username") or "",
                    "nickname": row.get("nickname") or "",
                    "display_name": (
                        row.get("nickname")
                        or row.get("username")
                        or f"用户#{row['id']}"
                    ),
                    "avatar": row.get("avatar") or "",
                    "role_id": row.get("role_id"),
                    "department_id": row.get("department_id"),
                }
                for row in rows
            ]
        }
    finally:
        conn.close()


@app.get("/api/logs")
async def list_logs(
    keyword: Optional[str] = None,
    operation: Optional[str] = None,
    user_id: Optional[int] = None,
    module: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    operation_type = _normalize_operation(operation)
    conn = get_db()
    try:
        ensure_employee_operation_logs_table(conn)
        base_where, base_params = _build_where(
            keyword, user_id, module, start_date, end_date
        )
        list_where, list_params = _build_where(
            keyword, user_id, module, start_date, end_date, operation_type
        )
        joins = """
            FROM employee_operation_logs l
            LEFT JOIN parts p ON p.id = l.part_id
            LEFT JOIN yh_admin_user u ON u.id = l.user_id
        """

        cursor = conn.cursor()
        grouped_select = f"""
            SELECT
                {PRODUCT_NAME_SQL} AS grouped_product_name,
                {MODEL_SQL} AS grouped_model,
                MAX(l.id) AS latest_log_id,
                COUNT(*) AS log_count,
                GROUP_CONCAT(
                    DISTINCT UPPER(l.operation_type)
                    ORDER BY FIELD(UPPER(l.operation_type),'CREATE','UPDATE','DELETE','COMPLETE','CORRECTED')
                    SEPARATOR ','
                ) AS operation_types,
                GROUP_CONCAT(
                    DISTINCT UPPER(l.module_code)
                    ORDER BY FIELD(UPPER(l.module_code),'PRODUCT','IMAGE','SPEC','PRICE','CLASSIFICATION')
                    SEPARATOR ','
                ) AS module_codes
            {joins}
            WHERE {list_where}
            GROUP BY {PRODUCT_NAME_SQL}, {MODEL_SQL}
        """

        cursor.execute(
            f"SELECT COUNT(*) AS total FROM ({grouped_select}) grouped_logs",
            list_params,
        )
        total = int(cursor.fetchone()["total"])

        image_columns = ", ".join(f"p.{field}" for field in IMAGE_FIELDS)
        cursor.execute(
            f"""
            SELECT
                l.id, l.user_id, l.part_id, l.operation_type, l.module_code,
                l.detail, l.created_at,
                u.username, u.nickname, u.avatar,
                grouped.grouped_product_name AS product_name,
                grouped.grouped_model AS model,
                p.sku_code, p.product_brand, p.product_type, {image_columns},
                grouped.log_count, grouped.operation_types, grouped.module_codes
            FROM ({grouped_select}) grouped
            JOIN employee_operation_logs l ON l.id=grouped.latest_log_id
            LEFT JOIN parts p ON p.id=l.part_id
            LEFT JOIN yh_admin_user u ON u.id=l.user_id
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT %s OFFSET %s
            """,
            [*list_params, page_size, (page - 1) * page_size],
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM (
                SELECT 1
                {joins}
                WHERE {base_where}
                GROUP BY {PRODUCT_NAME_SQL}, {MODEL_SQL}
            ) grouped_logs
            """,
            base_params,
        )
        base_group_total = int(cursor.fetchone()["total"])

        cursor.execute(
            f"""
            SELECT operation_type, COUNT(*) AS count
            FROM (
                SELECT UPPER(l.operation_type) AS operation_type
                {joins}
                WHERE {base_where}
                GROUP BY UPPER(l.operation_type), {PRODUCT_NAME_SQL}, {MODEL_SQL}
            ) operation_products
            GROUP BY operation_type
            """,
            base_params,
        )
        grouped = {
            (row["operation_type"] or "").upper(): row["count"]
            for row in cursor.fetchall()
        }

        return {
            "items": [_serialize_log_group(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
            "stats": {
                "all": base_group_total,
                "create": grouped.get("CREATE", 0),
                "update": grouped.get("UPDATE", 0),
                "delete": grouped.get("DELETE", 0),
                "complete": grouped.get("COMPLETE", 0),
                "corrected": grouped.get("CORRECTED", 0),
            },
        }
    finally:
        conn.close()


@app.get("/api/logs/{log_id}")
async def get_log(log_id: int):
    conn = get_db()
    try:
        ensure_employee_operation_logs_table(conn)
        image_columns = ", ".join(f"p.{field}" for field in IMAGE_FIELDS)
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                l.id, l.user_id, l.part_id, l.operation_type, l.module_code,
                l.detail, l.created_at,
                u.username, u.nickname, u.avatar,
                {PRODUCT_NAME_SQL} AS product_name,
                {MODEL_SQL} AS model,
                p.sku_code, p.product_brand,
                p.product_type, {image_columns}
            FROM employee_operation_logs l
            LEFT JOIN parts p ON p.id = l.part_id
            LEFT JOIN yh_admin_user u ON u.id = l.user_id
            WHERE l.id = %s
            """,
            (log_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="日志不存在")

        product_name = row.get("product_name") or ""
        model = row.get("model") or ""
        cursor.execute(
            f"""
            SELECT
                l.id, l.user_id, l.part_id, l.operation_type, l.module_code,
                l.detail, l.created_at,
                u.username, u.nickname, u.avatar,
                {PRODUCT_NAME_SQL} AS product_name,
                {MODEL_SQL} AS model,
                p.sku_code, p.product_brand, p.product_type, {image_columns}
            FROM employee_operation_logs l
            LEFT JOIN parts p ON p.id=l.part_id
            LEFT JOIN yh_admin_user u ON u.id=l.user_id
            WHERE {PRODUCT_NAME_SQL}=%s AND {MODEL_SQL}=%s
            ORDER BY l.created_at DESC, l.id DESC
            """,
            (product_name, model),
        )
        entries = [_serialize_log(item) for item in cursor.fetchall()]
        group = _serialize_log(row)
        # 最新一条若是删除日志，尝试从同组仍可关联主表的历史记录补充图片和品牌。
        for entry in entries:
            for field in ("image_url", "product_brand", "product_type", "sku_code"):
                if not group.get(field) and entry.get(field):
                    group[field] = entry[field]
        group["entries"] = entries
        group["log_count"] = len(entries)
        group["operation_types"] = list(dict.fromkeys(
            item["operation_type"] for item in entries
        ))
        group["module_codes"] = list(dict.fromkeys(
            item["module_code"] for item in entries
        ))
        return group
    finally:
        conn.close()
