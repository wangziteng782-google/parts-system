"""兼容原有启动命令：uvicorn app:app --host 0.0.0.0 --port 8055。"""

from parts_system.application import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8055,
        reload=False,
    )
