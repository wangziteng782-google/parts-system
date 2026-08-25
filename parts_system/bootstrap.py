from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import time

from .config import PROJECT_ROOT, logger
from .auth import authentication_middleware


app = FastAPI(title="电梯配件管理系统")
app.middleware("http")(authentication_middleware)
app.mount(
    "/static",
    StaticFiles(directory=f"{PROJECT_ROOT}/static"),
    name="static",
)


@app.middleware("http")
async def disable_static_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response
templates = Jinja2Templates(directory=f"{PROJECT_ROOT}/templates")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """在控制台记录请求、响应状态和耗时，不写入日志文件。"""
    started_at = time.perf_counter()
    client_ip = request.client.host if request.client else "unknown"
    client_port = request.client.port if request.client else "unknown"
    method = request.method
    request_target = request.url.path
    if request.url.query:
        safe_query = "&".join(
            f"{key}={'***' if key.lower() in {'t', 'admin-token', 'token'} else value}"
            for key, value in request.query_params.multi_items()
        )
        request_target += f"?{safe_query}"
    logger.info(
        f"[请求] {method} {request_target} | "
        f"client={client_ip}:{client_port} | http={request.scope.get('http_version', '-')}"
    )
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.exception(
            f"[响应异常] {method} {request_target} | "
            f"client={client_ip}:{client_port} | elapsed={elapsed_ms:.1f}ms"
        )
        raise
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    content_length = response.headers.get("content-length", "unknown")
    logger.info(
        f"[响应] {method} {request_target} | status={response.status_code} | "
        f"elapsed={elapsed_ms:.1f}ms | bytes={content_length}"
    )
    return response
