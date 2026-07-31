from typing import Optional

from .auth import get_current_user_id


# 本地调试页面没有登录态，暂时归到一个真实存在且可在日志筛选中显示的角色4用户。
# 正式接入 Token 后，只需在统一认证层把这里替换为解析出的 yh_admin_user.id。
LOCAL_FALLBACK_USER_ID = 51


def write_operation_log(
    cursor,
    *,
    part_id: Optional[int],
    operation_type: str,
    module_code: str,
    detail: str,
    user_id: Optional[int] = None,
):
    normalized_operation = (operation_type or "").strip().upper()
    if normalized_operation not in {"CREATE", "UPDATE", "DELETE"}:
        raise ValueError(f"不支持的日志操作类型：{operation_type}")

    cursor.execute(
        """
        INSERT INTO employee_operation_logs
            (user_id, part_id, operation_type, module_code, detail)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            user_id or get_current_user_id() or LOCAL_FALLBACK_USER_ID,
            part_id,
            normalized_operation,
            (module_code or "PRODUCT").strip().upper(),
            (detail or "").strip() or "未填写操作摘要",
        ),
    )


def display_change_value(value, limit: int = 180):
    if value is None or value == "":
        return "空"
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > limit:
        return f"{text[:limit]}…"
    return text
