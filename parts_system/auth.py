"""JWT handoff authentication shared by the three browser pages and APIs."""

from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import os
import time
from typing import Optional
from urllib.parse import urlencode

import jwt
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .shared import get_db, logger


JWT_QUERY_NAME = "t"
JWT_HEADER_NAME = os.getenv("JWT_TOKEN_NAME", "Admin-Token").strip() or "Admin-Token"
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "").strip()
JWT_ALGORITHM = "HS256"
JWT_TOKEN_EXP_SECONDS = int(os.getenv("JWT_TOKEN_EXP_SECONDS", "432000"))
AUTH_REQUIRED = os.getenv("PARTS_AUTH_REQUIRED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SESSION_COOKIE_NAME = os.getenv(
    "PARTS_SESSION_COOKIE_NAME",
    "parts_system_session",
).strip()
SESSION_SECRET_KEY = (
    os.getenv("PARTS_SESSION_SECRET_KEY", "").strip() or JWT_SECRET_KEY
)
SESSION_MAX_MINUTES = max(
    1,
    int(os.getenv("PARTS_SESSION_MAX_MINUTES", "7200")),
)


def _parse_role_ids(environment_name: str, default_value: str) -> set[int]:
    raw_value = os.getenv(environment_name, default_value)
    try:
        return {
            int(item.strip())
            for item in raw_value.split(",")
            if item.strip()
        }
    except ValueError as exc:
        raise RuntimeError(
            f"{environment_name} 必须是逗号分隔的整数角色ID"
        ) from exc


ADMIN_ROLE_IDS = _parse_role_ids("PARTS_ADMIN_ROLE_IDS", "1")
SALES_ROLE_IDS = _parse_role_ids("PARTS_SALES_ROLE_IDS", "3,31,32")
PURCHASE_ROLE_IDS = _parse_role_ids(
    "PARTS_PURCHASE_ROLE_IDS",
    "4,36,37",
) | {4,36, 37}
INTERNAL_ROLE_IDS = ADMIN_ROLE_IDS | SALES_ROLE_IDS | PURCHASE_ROLE_IDS

PUBLIC_PATHS = {"/favicon.ico", "/api/health"}
PROTECTED_PAGES = {"/", "/goods", "/logs", "/sales", "/inquiries"}
PROTECTED_SCHEMA_PATHS = {"/docs", "/redoc", "/openapi.json"}

_current_user: ContextVar[Optional[dict]] = ContextVar(
    "parts_system_current_user",
    default=None,
)


class AuthenticationError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def get_current_user() -> Optional[dict]:
    return _current_user.get()


def get_current_user_id() -> Optional[int]:
    user = get_current_user()
    return int(user["id"]) if user and user.get("id") is not None else None


def _is_protected_path(path: str) -> bool:
    if path.startswith("/static/") or path in PUBLIC_PATHS:
        return False
    return (
        path in PROTECTED_PAGES
        or path in PROTECTED_SCHEMA_PATHS
        or path.startswith("/api/")
    )


def _decode_external_token(token: str) -> dict:
    if not JWT_SECRET_KEY:
        raise AuthenticationError("JWT认证密钥尚未配置", status_code=503)
    normalized_token = str(token or "").strip().strip('"').strip("'")
    if normalized_token.lower().startswith("bearer "):
        normalized_token = normalized_token[7:].strip()
    try:
        claims = jwt.decode(
            normalized_token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["iat"]},
            leeway=10,
        )
    except jwt.ExpiredSignatureError as exc:
        logger.warning("[JWT解析失败] error=ExpiredSignatureError")
        raise AuthenticationError("登录凭证已过期，请从正式系统重新进入") from exc
    except jwt.ImmatureSignatureError as exc:
        logger.warning("[JWT解析失败] error=ImmatureSignatureError")
        raise AuthenticationError("登录凭证尚未生效，请检查服务器时间") from exc
    except jwt.InvalidTokenError as exc:
        logger.warning(
            f"[JWT解析失败] error={type(exc).__name__} | "
            f"detail={exc} | token_length={len(normalized_token)} | "
            f"token_segments={len(normalized_token.split('.'))}"
        )
        raise AuthenticationError("登录凭证无效，请从正式系统重新进入") from exc

    # 兼容签发方暂未写入标准exp的现状；有exp时PyJWT已自动验证。
    if claims.get("exp") is None:
        try:
            expires_at = int(claims["iat"]) + JWT_TOKEN_EXP_SECONDS
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("登录凭证缺少有效的签发时间") from exc
        if time.time() >= expires_at:
            raise AuthenticationError("登录凭证已过期，请从正式系统重新进入")
        claims["_calculated_exp"] = expires_at
    return claims


def _load_internal_user(claims: dict) -> dict:
    data = claims.get("data")
    raw_user_id = data.get("admin_user_id") if isinstance(data, dict) else None
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("登录凭证中缺少有效的用户ID") from exc

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, username, nickname, avatar, role_id, department_id,
                      is_disable, is_delete, delete_time
               FROM yh_admin_user
               WHERE id=%s
               LIMIT 1""",
            (user_id,),
        )
        user = cursor.fetchone()
    finally:
        conn.close()

    if not user:
        raise AuthenticationError("当前用户不属于内部用户", status_code=403)
    if int(user.get("is_disable") or 0) != 0:
        raise AuthenticationError("当前内部账号已被禁用", status_code=403)
    if int(user.get("is_delete") or 0) != 0 or user.get("delete_time") not in {
        None,
        0,
        "0",
    }:
        raise AuthenticationError("当前内部账号已被删除", status_code=403)
    try:
        role_id = int(user.get("role_id"))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("当前内部账号没有有效角色", status_code=403) from exc
    if role_id not in INTERNAL_ROLE_IDS:
        raise AuthenticationError("当前角色没有进入本系统的权限", status_code=403)
    return user


def _role_group(user: dict) -> str:
    role_id = int(user["role_id"])
    if role_id in ADMIN_ROLE_IDS:
        return "admin"
    if role_id in PURCHASE_ROLE_IDS:
        return "purchase"
    if role_id in SALES_ROLE_IDS:
        return "sales"
    return "unknown"


def _authorize_request(user: Optional[dict], path: str) -> None:
    if user is None:
        return
    role_group = _role_group(user)
    if role_group in {"admin", "purchase"}:
        return
    if role_group == "sales":
        if path in {"/", "/sales"}:
            return
        if path == "/api/sales" or path.startswith("/api/sales/"):
            return
        raise AuthenticationError(
            "销售账号只能访问销售查询页面",
            status_code=403,
        )
    raise AuthenticationError("当前角色没有访问权限", status_code=403)


def _session_expiration(_external_claims: dict) -> int:
    """外部Token只用于首次换取会话；本系统会话按独立时长过期。"""
    return int(
        (
            datetime.now(timezone.utc)
            + timedelta(minutes=SESSION_MAX_MINUTES)
        ).timestamp()
    )


def _encode_session(user: dict, external_claims: dict) -> tuple[str, int]:
    if not SESSION_SECRET_KEY:
        raise AuthenticationError("会话签名密钥尚未配置", status_code=503)
    now = datetime.now(timezone.utc)
    expires_at = _session_expiration(external_claims)
    payload = {
        "token_type": "parts_system_session",
        "user_id": int(user["id"]),
        "username": user.get("username"),
        "nickname": user.get("nickname"),
        "role_id": user.get("role_id"),
        "department_id": user.get("department_id"),
        "iat": int(now.timestamp()),
        "exp": expires_at,
    }
    return (
        jwt.encode(payload, SESSION_SECRET_KEY, algorithm=JWT_ALGORITHM),
        expires_at,
    )


def _decode_session(token: str) -> dict:
    if not SESSION_SECRET_KEY:
        raise AuthenticationError("会话签名密钥尚未配置", status_code=503)
    try:
        claims = jwt.decode(
            token,
            SESSION_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat", "user_id", "token_type"]},
            leeway=10,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("登录会话已过期，请从正式系统重新进入") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("登录会话无效，请从正式系统重新进入") from exc
    if claims.get("token_type") != "parts_system_session":
        raise AuthenticationError("登录会话类型无效")
    return {
        "id": int(claims["user_id"]),
        "username": claims.get("username"),
        "nickname": claims.get("nickname"),
        "role_id": claims.get("role_id"),
        "department_id": claims.get("department_id"),
    }


def _error_response(request: Request, error: AuthenticationError):
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.message},
        )
    return HTMLResponse(
        status_code=error.status_code,
        content=f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>访问失败</title>
<style>
body{{margin:0;background:#f5f7fa;font-family:Arial,"Microsoft YaHei",sans-serif}}
.box{{max-width:520px;margin:14vh auto;padding:34px;background:#fff;border-radius:12px;
box-shadow:0 8px 28px rgba(15,23,42,.1);text-align:center}}
h1{{font-size:20px;color:#1f2937}}p{{color:#64748b;line-height:1.8}}
</style></head><body><div class="box"><h1>暂时无法访问</h1>
<p>{error.message}</p><p>请返回公司正式系统并重新打开该页面。</p>
</div></body></html>""",
    )


def _clean_redirect_url(request: Request) -> str:
    clean_query = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key.lower() != JWT_QUERY_NAME
    ]
    return request.url.path + (f"?{urlencode(clean_query)}" if clean_query else "")


def _is_secure_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded_proto.split(",")[0].strip() == "https"


async def authentication_middleware(request: Request, call_next):
    path = request.url.path
    if not _is_protected_path(path):
        return await call_next(request)

    external_token = (
        request.query_params.get(JWT_QUERY_NAME)
        or request.headers.get(JWT_HEADER_NAME)
    )
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    session_to_set = None
    session_expires_at = None

    try:
        if external_token:
            external_claims = _decode_external_token(external_token)
            user = _load_internal_user(external_claims)
            logger.info(
                f"[认证通过] user_id={user.get('id')} | "
                f"role_id={user.get('role_id')} | role_group={_role_group(user)} | "
                f"path={path} | source=external_token"
            )
            session_to_set, session_expires_at = _encode_session(
                user,
                external_claims,
            )
        elif session_token:
            user = _decode_session(session_token)
        elif AUTH_REQUIRED:
            raise AuthenticationError("缺少登录凭证，请从正式系统进入")
        else:
            user = None
        _authorize_request(user, path)
    except AuthenticationError as error:
        logger.warning(
            f"[认证失败] path={path} | status={error.status_code} | "
            f"reason={error.message}"
        )
        response = _error_response(request, error)
        if session_token and error.status_code == 401:
            response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return response

    if user and path == "/":
        destination = "/sales" if _role_group(user) == "sales" else "/goods"
        response = RedirectResponse(url=destination, status_code=303)
    elif external_token and path in PROTECTED_PAGES:
        response = RedirectResponse(
            url=_clean_redirect_url(request),
            status_code=303,
        )
    else:
        request.state.current_user = user
        context_token = _current_user.set(user)
        try:
            response = await call_next(request)
        finally:
            _current_user.reset(context_token)

    if session_to_set and session_expires_at:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_to_set,
            max_age=max(1, session_expires_at - int(time.time())),
            expires=datetime.fromtimestamp(
                session_expires_at,
                tz=timezone.utc,
            ),
            path="/",
            secure=_is_secure_request(request),
            httponly=True,
            samesite="lax",
        )
    return response
