# parts-system 宝塔测试部署

## 推荐结构

- 宝塔继续管理现有 PHP、Nginx 和 MySQL。
- FastAPI 使用独立 Python 3.11 虚拟环境。
- Uvicorn 只监听 `127.0.0.1:8055`，不直接开放公网端口。
- systemd 负责开机启动、异常重启和运行状态。
- Nginx 将测试域名反向代理到 Uvicorn。
- 部署数据库使用 `parts_database`，数据来自当前本地完整数据库。

## 一、服务器部署目录

```bash
mkdir -p /www/wwwroot/parts-system-test
cd /www/wwwroot/parts-system-test
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

上传代码时不要上传：

- `.git`、`.idea`、`__pycache__`
- `.env`
- `qiniu_config.local.json`
- `migration_target.local.json`
- 本地日志、Excel导入文件和迁移状态文件

## 二、生产环境变量

复制 `deploy/.env.production.example`：

```bash
cp deploy/.env.production.example .env
chmod 600 .env
chown www:www .env
```

填写部署数据库专用账号和七牛云配置。数据库账号只授予
`parts_database` 的增删改查、建表和索引权限，不使用 MySQL root。

## 三、同步数据库

先在宝塔创建：

- 数据库：`parts_database`
- 用户：`parts_database`
- 权限范围：仅 `parts_database`

推荐直接运行项目内的兼容导出脚本，它会使用一致性快照、隐藏命令行密码、
兼容 MySQL 5.7 字符集并生成各表行数和 SHA256 校验清单：

```powershell
python deploy\tools\export_deployment_database.py
```

输出文件位于 `deploy/artifacts/`。

该SQL是每次执行命令时生成的数据库一致性快照，不会在数据库后续变化时自动更新。
脚本读取 `PARTS_DB_*` 环境变量指定的数据库；执行前应确认连接目标确实为要部署的
`parts_database`。数据库有新修改后，需要重新执行导出命令。

不建议通过 phpMyAdmin 导入完整数据库。当前 SQL 文件接近 20 MB，
phpMyAdmin 容易受到 PHP 上传大小和执行超时限制，页面可能显示导入结束，
但实际没有执行到建表语句。

将 `deploy/artifacts/parts_database.sql` 上传到服务器（例如
`/www/backup/parts_database.sql`），然后在宝塔“终端”中执行：

```bash
mysql --default-character-set=utf8mb4 -u parts_database -p parts_database < /www/backup/parts_database.sql
```

输入 `parts_database` 用户的数据库密码。命令没有输出且返回命令提示符表示执行完成。
随后验证表数和核心数据量：

```bash
mysql -u parts_database -p -D parts_database -e "SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema='parts_database'; SELECT COUNT(*) AS parts_count FROM parts; SELECT COUNT(*) AS image_count FROM parts_new;"
```

正确结果应为：

- `table_count = 9`
- `parts_count = 5326`
- `image_count = 23200`

如果第一条命令报错，不要重复导入；保留终端中包含 `ERROR` 的完整一行，
可据此判断是 MySQL 版本、权限还是 SQL 语法问题。导入前确认目标数据库名称，
不要导入到其他 PHP 正式库。首次部署采用一次性全量导入；部署成功后，线上库成为服务的
唯一写入库，不做本地与服务器双向同步。

## 四、先在服务器本机验证

```bash
cd /www/wwwroot/parts-system-test
set -a
source .env
set +a
.venv/bin/python -m compileall parts_system
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8055
```

另开终端：

```bash
curl http://127.0.0.1:8055/api/health
```

必须返回 `"status":"ok"`，并核对 `parts_count` 和 `operation_log_count`。

## 五、安装 systemd 服务

```bash
cp deploy/parts-system.service /etc/systemd/system/parts-system.service
systemctl daemon-reload
systemctl enable --now parts-system
systemctl status parts-system
journalctl -u parts-system -n 100 --no-pager
```

项目代码由 `www` 用户运行。上传后确保 `product_classifications.json` 及其目录对 `www`
用户可写，因为分类树编辑功能需要保存该文件。

## 六、宝塔配置反向代理

域名未申请时，使用公网IP加独立Nginx端口测试：

```text
http://120.46.152.222:8066/
```

宝塔中新建站点 `120.46.152.222:8066`，使用 Nginx，并把
`deploy/nginx-parts-system.conf` 的代理配置加入站点配置。宝塔防火墙和华为云安全组
只开放TCP 8066，Python的8055端口保持不开放。然后访问：

```text
http://120.46.152.222:8066/
http://120.46.152.222:8066/logs
http://120.46.152.222:8066/api/health
```

正式域名下来后，将Nginx改为监听80/443并替换 `server_name`，然后在宝塔申请SSL；
Python内部服务端口仍然保持8055。

## 七、PHP 项目联通

如果 PHP 和 Python 在同一台服务器，PHP 后端应调用：

```text
http://127.0.0.1:8055/api/health
```

后续 Token 接口同样走本机地址，避免绕公网。浏览器打开三个页面时走 Nginx 域名，
Token 由正式 PHP 系统签发，Python 只负责校验用户 ID 和权限。

当前认证入口：

```text
https://<独立域名>/goods?t=<JWT>
https://<独立域名>/logs?t=<JWT>
https://<独立域名>/sales?t=<JWT>
```

JWT使用HS256，用户ID读取 `data.admin_user_id`。服务器 `.env` 必须配置：

```env
PARTS_AUTH_REQUIRED=true
JWT_TOKEN_NAME=Admin-Token
JWT_SECRET_KEY='与PHP签发方一致的HS256密钥'
JWT_TOKEN_EXP_SECONDS=120
PARTS_SESSION_SECRET_KEY='另一串独立的高强度随机密钥'
PARTS_SESSION_MAX_MINUTES=120
PARTS_ADMIN_ROLE_IDS=1
PARTS_SALES_ROLE_IDS=3,31,32
PARTS_PURCHASE_ROLE_IDS=4,36,37
```

首次验证成功后系统写入HttpOnly会话Cookie，并立即跳转到不含`t`的干净地址。
Nginx站点应关闭访问日志或使用不记录查询字符串的日志格式，避免JWT进入访问日志。

权限由Python后端再次校验，不能只依赖PHP隐藏菜单：

- 超级管理员角色1：可访问 `/goods`、`/logs`、`/sales` 和全部业务API。
- 采购角色4、36、37：可访问三个页面和全部业务API。
- 销售角色3、31、32：仅可访问 `/sales` 及 `/api/sales/*`。
- 其他角色、禁用用户和已删除用户统一拒绝。

## 八、回滚

上线前保留：

- 当前代码目录压缩备份
- 测试数据库导入前备份
- Nginx站点配置备份
- systemd服务文件备份

应用回滚只需切换代码目录并重启：

```bash
systemctl restart parts-system
```
