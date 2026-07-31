from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ..bootstrap import app, templates
from ..shared import PROJECT_ROOT


@app.get("/", include_in_schema=False)
async def root_page():
    """兼容旧根路径，统一跳转到配件维护页。"""
    return RedirectResponse(url="/goods", status_code=302)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(
        f"{PROJECT_ROOT}/static/img/favicon.ico",
        media_type="image/x-icon",
    )


@app.get("/sales", response_class=HTMLResponse)
async def sales_page(request: Request):
    """销售查询页面预留入口。"""
    return templates.TemplateResponse(
        request=request,
        name="sales.html",
        context={},
    )
