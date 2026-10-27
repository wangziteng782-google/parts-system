"""健康检查模块

返回系统运行状态、数据库连接状态、版本号等基本信息，
供 Nginx / systemd / 监控系统定时探测使用。
"""
from datetime import datetime

from fastapi import HTTPException

from ..bootstrap import app
from ..model import get_db


@app.get("/health")
@app.get("/api/health")
async def deployment_health():
    """Deployment and PHP-integration health check without exposing secrets."""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS count FROM parts")
        parts_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM employee_operation_logs")
        log_count = cursor.fetchone()["count"]
        return {
            "status": "ok",
            "service": "parts-system",
            "database": "ok",
            "parts_count": parts_count,
            "operation_log_count": log_count,
            "server_time": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception:
        raise HTTPException(status_code=503, detail="服务或数据库暂不可用")
    finally:
        if conn:
            conn.close()
