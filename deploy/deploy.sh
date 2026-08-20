#!/bin/bash
# 一键部署脚本（正式环境）
# 用法: bash deploy.sh [分支名，默认master]

set -e

BRANCH=${1:-master}
APP_DIR=/www/wwwroot/parts-system-test
SERVICE_NAME=parts-system
PORT=8055
STAMP=$(date +%Y%m%d_%H%M%S)

echo "=== 开始部署 $STAMP (分支: $BRANCH) ==="

# 1. 拉取最新代码
echo "[1/5] 拉取代码..."
cd "$APP_DIR"
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"

# 2. 安装依赖
echo "[2/5] 检查依赖..."
.venv/bin/pip install -r requirements.txt

# 3. 语法检查（失败则中止部署）
echo "[3/5] 语法检查..."
.venv/bin/python -m compileall app.py parts_system

# 4. 重启服务
echo "[4/5] 重启服务..."
systemctl restart "$SERVICE_NAME"
sleep 2

# 5. 健康检查
echo "[5/5] 健康检查..."
HEALTH_URL="http://127.0.0.1:$PORT/api/health"
if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
    echo "✅ 部署成功！"
else
    echo "❌ 健康检查失败！"
    echo "   查看日志: journalctl -u $SERVICE_NAME -n 50 --no-pager"
    echo "   回滚: git log --oneline -5  # 找到上一个commit"
    echo "         git checkout <上一个commit> && systemctl restart $SERVICE_NAME"
    exit 1
fi

echo "=== 部署完成 $STAMP ==="
