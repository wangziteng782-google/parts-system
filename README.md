# parts-system 配件批改系统

## 系统架构

- Nginx 和 MySQL。
- FastAPI 使用独立 Python 3.11 虚拟环境。
- Uvicorn 只监听 `127.0.0.1:8055`，不直接开放公网端口。
- systemd 负责开机启动、异常重启和运行状态。
- Nginx 将测试域名反向代理到 Uvicorn。
