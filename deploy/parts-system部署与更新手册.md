# parts-system 部署与更新手册

> 更新时间：2026-07-30  
> 适用项目：电梯配件管理系统（FastAPI + MySQL + Nginx）  
> 本手册记录当前已经成功完成的一版服务器部署，并作为后续人工发布和故障回滚的操作依据。

## 一、当前线上架构

```text
员工浏览器
    ↓ HTTPS
独立业务域名
    ↓ Nginx反向代理
http://127.0.0.1:8055
    ↓ systemd管理的Uvicorn/FastAPI
/www/wwwroot/parts-system-test
    ↓ PyMySQL
MySQL：parts_database
```

当前约定：

| 项目 | 当前值 |
|---|---|
| 本地项目目录 | `C:\wzt_WorkFile\project\parts-system` |
| 服务器项目目录 | `/www/wwwroot/parts-system-test` |
| Python版本 | Python 3.9.9 |
| 虚拟环境 | `/www/wwwroot/parts-system-test/.venv` |
| systemd服务名 | `parts-system` |
| Python监听地址 | `127.0.0.1:8055` |
| 数据库名 | `parts_database` |
| 数据库用户 | `parts_database` |
| Nginx入口 | 独立域名，反向代理至 `http://127.0.0.1:8055` |
| 配件维护页 | `https://<独立域名>/goods` |
| 日志页面 | `https://<独立域名>/logs` |
| 销售查询页 | `https://<独立域名>/sales` |
| 健康检查 | `https://<独立域名>/api/health` |

说明：

- `127.0.0.1` 表示服务器自身，不是员工电脑，也不是公网IP。
- 8055只供服务器内部Nginx访问，不需要向公网开放。
- 员工只访问独立HTTPS域名。
- Python项目不能通过 `templates/index.html` 当静态文件访问，页面必须经过FastAPI返回。
- `.env` 和 `.venv` 不放入部署压缩包。

---

## 二、本次首次部署已经执行的流程

### 1. 导出本地完整数据库

在本地项目目录执行：

```powershell
cd C:\wzt_WorkFile\project\parts-system
python deploy\tools\export_deployment_database.py
```

输出：

```text
deploy/artifacts/parts_database.sql
deploy/artifacts/parts_database.manifest.json
```

关于“是否为最新数据库”的说明：

- 脚本每执行一次，都会重新连接当时配置的数据库并覆盖生成新的 SQL，不读取旧SQL继续追加。
- 它导出的是“本次命令开始执行时”的一致性快照，不是持续同步文件；数据库之后又有修改，必须重新执行脚本。
- 默认读取本机环境变量 `PARTS_DB_HOST`、`PARTS_DB_PORT`、`PARTS_DB_USER`、`PARTS_DB_PASSWORD`、`PARTS_DB_NAME`。未设置时默认数据库名为 `parts_database`。
- 只有脚本连接的确实是本地 `parts_database`，且导出后数据库没有继续变化时，SQL才与该时点的本地库一致。
- 导出前后可查看 `parts_database.manifest.json` 中的数据库名、各表行数和SQL文件SHA256，确认没有拿错文件。

导出脚本完成了以下工作：

- 使用一致性快照导出当前 `parts_database`。
- 导出表结构、数据、触发器等内容。
- 将MySQL 8/9专用字符集调整为MySQL 5.7可使用的字符集。
- 移除恢复阶段不必要的 `LOCK TABLES`，避免普通数据库账号权限不足。
- 生成各表行数和SQL文件SHA256校验值。

### 2. 在宝塔创建数据库

宝塔“数据库”页面创建：

```text
数据库名：parts_database
用户名：parts_database
字符集：utf8mb4
```

服务器MySQL版本已确认：

```text
MySQL 5.7.44-log
```

### 3. 上传并导入SQL

将SQL上传到：

```text
/www/backup/parts_database.sql
```

终端导入：

```bash
/www/server/mysql/bin/mysql \
  --default-character-set=utf8mb4 \
  -u parts_database -p \
  parts_database < /www/backup/parts_database.sql
```

检查表：

```bash
/www/server/mysql/bin/mysql \
  -u parts_database -p \
  -D parts_database \
  -e "SHOW TABLES;"
```

首次导入结果为9张表。以后普通代码更新禁止重新导入这份全量SQL，否则可能覆盖或破坏线上已经修改的数据。

### 4. 打包并上传代码

本地执行：

```powershell
python deploy\tools\build_deployment_package.py
```

生成：

```text
deploy/artifacts/parts-system-code.zip
```

关于“是否为最新代码”的说明：

- 脚本每执行一次都会重新扫描项目目录，并以覆盖方式重新生成 ZIP。
- ZIP包含执行命令时已经保存到磁盘的当前代码；编辑器中尚未保存的改动不会进入压缩包。
- 修改代码后必须重新执行打包命令，旧ZIP不会自动跟随代码变化。
- 部署工具统一放在 `deploy/tools/`，数据导入和数据迁移任务继续放在 `jobs/`，两类脚本不要混用。

压缩包会自动排除：

- `.env`
- `.venv`
- 七牛云本地密钥配置
- 数据库迁移目标密钥配置
- `__pycache__`
- 本地日志
- 导入/迁移状态文件
- `deploy/artifacts` 内的大文件

将压缩包上传并解压到：

```text
/www/wwwroot/parts-system-test
```

解压后，`app.py` 应直接位于：

```text
/www/wwwroot/parts-system-test/app.py
```

不能多套一层同名目录。

### 5. 配置环境变量

服务器执行：

```bash
cd /www/wwwroot/parts-system-test
cp deploy/.env.production.example .env
chmod 600 .env
```

`.env` 中配置：

```env
PARTS_DB_HOST=127.0.0.1
PARTS_DB_PORT=3306
PARTS_DB_USER=parts_database
PARTS_DB_PASSWORD='数据库真实密码'
PARTS_DB_NAME=parts_database
PARTS_DB_CHARSET=utf8mb4
PARTS_DB_CONNECT_TIMEOUT=10

PARTS_AUTH_REQUIRED=true
JWT_TOKEN_NAME=Admin-Token
JWT_SECRET_KEY='与PHP项目一致的HS256密钥'
JWT_TOKEN_EXP_SECONDS=120
PARTS_SESSION_SECRET_KEY='单独生成的高强度会话密钥'
PARTS_SESSION_MAX_MINUTES=120
PARTS_ADMIN_ROLE_IDS=1
PARTS_SALES_ROLE_IDS=3,31,32
PARTS_PURCHASE_ROLE_IDS=4,36,37

QINIU_ACCESS_KEY='七牛云AccessKey'
QINIU_SECRET_KEY='七牛云SecretKey'
QINIU_BUCKET=yiti-soft
QINIU_DOMAIN=http://soft.yitikeji.cn
```

注意：

- `.env` 不上传到公开仓库，不通过聊天或截图传播。
- 七牛云域名填写纯URL，不填写Markdown方括号。
- 密码包含特殊字符时使用单引号包裹。
- PHP打开页面时使用 `/goods?t=<JWT>`、`/logs?t=<JWT>`、`/sales?t=<JWT>`。
- JWT用户ID读取 `data.admin_user_id`，用户必须存在于 `yh_admin_user` 且未禁用、未删除。
- Token验证成功后会立即跳转到不含`t`的地址，并改用HttpOnly会话Cookie。
- `JWT_SECRET_KEY` 必须与PHP签发方一致；`PARTS_SESSION_SECRET_KEY` 应使用另一串独立随机值。
- 本系统应用日志会隐藏`t`，Nginx也必须关闭该站点访问日志或使用不记录查询字符串的日志格式。
- 超级管理员角色1和采购角色4、36、37可以访问三个页面及现有业务API。
- 销售角色3、31、32只能访问 `/sales` 和专用的 `/api/sales/*`，手改为 `/goods`、`/logs` 或调用批改API会返回403。

### 6. 创建Python虚拟环境

服务器执行：

```bash
cd /www/wwwroot/parts-system-test
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

虚拟环境用于隔离本项目依赖，不会随代码压缩包上传，每台服务器首次部署时创建一次。

### 7. 手动验证程序

```bash
cd /www/wwwroot/parts-system-test
set -a
source .env
set +a
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8055
```

另开终端检查：

```bash
curl http://127.0.0.1:8055/api/health
```

手动启动只用于首次验证。宝塔网页终端关闭或切换页面后，前台进程可能终止，正式运行必须交给systemd。

### 8. 安装systemd后台服务

```bash
cd /www/wwwroot/parts-system-test
chown www:www .env product_classifications.json
chmod 600 .env
cp deploy/parts-system.service /etc/systemd/system/parts-system.service
systemctl daemon-reload
systemctl enable --now parts-system
systemctl status parts-system --no-pager -l
```

状态应为：

```text
Active: active (running)
```

systemd提供：

- 退出宝塔终端后继续运行。
- 服务器重启后自动启动。
- 程序异常退出后自动重启。
- 统一查看控制台日志。

### 9. 配置宝塔Nginx反向代理

宝塔：

```text
网站 → 反向代理 → 添加反代
```

填写：

```text
域名：分配给本系统的独立域名
目标类型：URL地址
目标协议：http://
目标地址：127.0.0.1:8055
发送域名(host)：$http_host
备注：电梯配件管理系统
```

这里的目标地址不填写公网IP。因为Nginx和Python在同一台服务器，内部访问 `127.0.0.1:8055` 更安全、稳定。

### 10. 配置HTTPS

在反向代理项目或站点的SSL设置中，为独立域名申请证书，并开启HTTPS。最终验证：

```text
https://<独立域名>/goods
https://<独立域名>/logs
https://<独立域名>/sales
https://<独立域名>/api/health
```

---

## 三、以后修改代码后的标准发布流程

### 重要原则

普通代码更新不需要重复执行以下工作：

- 不需要重新导入完整数据库。
- 不需要重新创建数据库。
- 不需要重新创建虚拟环境。
- 不需要重新添加Nginx反向代理。
- 不需要重新安装systemd服务。
- 不需要重新申请SSL证书。

通常只需要：

```text
本地修改和检查
→ 生成新压缩包
→ 上传服务器
→ 停止服务
→ 备份旧版本
→ 替换代码并保留.env/.venv/线上分类JSON
→ 安装可能新增的依赖
→ 启动服务
→ 健康检查
```

### 1. 本地修改完成后检查

在本地执行：

```powershell
cd C:\wzt_WorkFile\project\parts-system
python -m compileall app.py parts_system
node --check static\js\products.js
node --check static\js\variants.js
node --check static\js\images.js
node --check static\js\logs.js
```

如果改动涉及具体业务，再在本地浏览器验证对应的新增、修改、图片、规格、价格或日志功能。

### 2. 生成新的部署包

```powershell
python deploy\tools\build_deployment_package.py
```

上传生成的：

```text
deploy/artifacts/parts-system-code.zip
```

建议在服务器按时间命名，例如：

```text
/www/backup/parts-system-code-20260730-1500.zip
```

不要把本地 `.env`、`.venv` 或密钥JSON手工加入压缩包。

### 3. 停止服务并备份旧版本

下面的组合命令应逐行执行。先按实际上传文件名修改 `PACKAGE`：

```bash
APP_DIR=/www/wwwroot/parts-system-test
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/www/backup/parts-system-test_$STAMP
PACKAGE=/www/backup/parts-system-code-20260730-1500.zip

echo "本次备份目录：$BACKUP_DIR"
systemctl stop parts-system
mv "$APP_DIR" "$BACKUP_DIR"
mkdir -p "$APP_DIR"
unzip "$PACKAGE" -d "$APP_DIR"
```

此时旧版本完整保存在 `$BACKUP_DIR`，不要立即删除。

### 4. 恢复服务器运行配置和线上分类数据

```bash
mv "$BACKUP_DIR/.env" "$APP_DIR/.env"
mv "$BACKUP_DIR/.venv" "$APP_DIR/.venv"
cp "$BACKUP_DIR/product_classifications.json" "$APP_DIR/product_classifications.json"
```

必须保留的内容：

| 文件/目录 | 原因 |
|---|---|
| `.env` | 包含服务器数据库密码和七牛云配置 |
| `.venv` | 包含服务器已经安装好的Python依赖 |
| `product_classifications.json` | 页面上编辑分类树时会修改，线上内容可能比本地新 |

如果本次需求明确修改了分类JSON基础数据，应先对比新旧文件，再决定使用哪一份，不能直接覆盖。

### 5. 检查权限、依赖和Python语法

```bash
cd "$APP_DIR"
chown -R www:www "$APP_DIR"
chmod 600 .env
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m compileall app.py parts_system
```

`pip install -r requirements.txt` 可以重复执行：

- 已安装且版本满足要求的依赖不会重复安装。
- 新增依赖会自动安装。
- 如果 `requirements.txt` 未变化，这一步通常很快。

### 6. 启动并验证

```bash
systemctl start parts-system
systemctl status parts-system --no-pager -l
curl http://127.0.0.1:8055/api/health
```

再从员工电脑验证：

```text
https://<独立域名>/goods
https://<独立域名>/logs
```

前端静态文件更新后建议按 `Ctrl+F5` 强制刷新浏览器缓存。

### 7. 发布成功后

至少保留上一版备份一段时间。确认主要业务功能正常后，再人工清理过旧备份。

不建议用模糊通配符一次删除大量备份。先查看：

```bash
ls -lh /www/backup/
```

确认具体备份目录后再处理。

---

## 四、更新失败时回滚

假设本次旧版本备份目录为：

```text
/www/backup/parts-system-test_20260730_150000
```

执行：

```bash
systemctl stop parts-system
mv /www/wwwroot/parts-system-test /www/backup/parts-system-failed_20260730_151000
mv /www/backup/parts-system-test_20260730_150000 /www/wwwroot/parts-system-test
systemctl start parts-system
systemctl status parts-system --no-pager -l
curl http://127.0.0.1:8055/api/health
```

如果本次还执行了数据库结构或数据迁移，仅回滚代码可能不够，必须使用数据库备份或对应的回滚SQL。

---

## 五、数据库发生变化时的发布规则

### 1. 仅修改Python、HTML、CSS、JavaScript

不操作数据库，按照“标准代码发布流程”更新并重启服务。

### 2. 新增Python依赖

更新 `requirements.txt`，发布时执行：

```bash
.venv/bin/pip install -r requirements.txt
```

### 3. 修改systemd服务文件

只有 `deploy/parts-system.service` 发生变化时才执行：

```bash
cp deploy/parts-system.service /etc/systemd/system/parts-system.service
systemctl daemon-reload
systemctl restart parts-system
```

### 4. 修改Nginx反向代理

只有域名、代理、上传大小或超时设置变化时才修改Nginx。修改后先检查：

```bash
/www/server/nginx/sbin/nginx -t
```

确认成功后再通过宝塔重载Nginx。

### 5. 修改数据库表结构

执行任何迁移SQL前先备份：

```bash
/www/server/mysql/bin/mysqldump \
  --single-transaction \
  --default-character-set=utf8mb4 \
  -u parts_database -p \
  parts_database > /www/backup/parts_database_before_migration.sql
```

然后执行经过审核的迁移SQL：

```bash
/www/server/mysql/bin/mysql \
  --default-character-set=utf8mb4 \
  -u parts_database -p \
  parts_database < /www/backup/本次迁移.sql
```

禁止在普通代码更新时重新导入首次部署的全量SQL。

---

## 六、常用运维命令

### 服务管理

```bash
systemctl status parts-system --no-pager -l
systemctl restart parts-system
systemctl stop parts-system
systemctl start parts-system
systemctl enable parts-system
```

### 查看日志

最近100行：

```bash
journalctl -u parts-system -n 100 --no-pager
```

持续观察：

```bash
journalctl -u parts-system -f
```

本项目只向控制台输出日志，不再生成容易膨胀的 `app.log` 文件。

### 健康检查

服务器内部：

```bash
curl http://127.0.0.1:8055/api/health
```

经过Nginx：

```bash
curl https://<独立域名>/api/health
```

### 检查8055端口

```bash
ss -lntp | grep 8055
```

### 检查Nginx配置

```bash
/www/server/nginx/sbin/nginx -t
```

---

## 七、组合命令和符号的简单解释

### `cd`

进入指定目录：

```bash
cd /www/wwwroot/parts-system-test
```

后续相对路径都以该目录为基准。

### `cp`

复制文件：

```bash
cp deploy/parts-system.service /etc/systemd/system/parts-system.service
```

左边是源文件，右边是目标位置。

### `mv`

移动或重命名文件/目录：

```bash
mv "$APP_DIR" "$BACKUP_DIR"
```

这里用于把当前版本整体改名为备份版本。同一磁盘内通常很快。

### `mkdir -p`

创建目录；父目录存在或目标目录已存在时不报错：

```bash
mkdir -p "$APP_DIR"
```

### `chmod`

设置Linux文件权限：

```bash
chmod 600 .env
```

`600` 表示只有文件所有者可以读写，其他用户不能读取。

### `chown`

修改文件所有者：

```bash
chown www:www .env
```

第一个 `www` 是用户，第二个 `www` 是用户组。

### `python3 -m venv .venv`

使用当前Python创建名为 `.venv` 的隔离环境。

### `.venv/bin/pip install -r requirements.txt`

使用项目自己的pip，按照 `requirements.txt` 安装依赖，不污染系统Python。

### `set -a`、`source .env`、`set +a`

```bash
set -a
source .env
set +a
```

含义：

1. `set -a`：之后读取的变量自动导出为环境变量。
2. `source .env`：在当前Shell中读取 `.env`。
3. `set +a`：关闭自动导出。

这组命令主要用于手动测试。systemd正式运行时通过 `EnvironmentFile` 自动读取 `.env`。

### `systemctl daemon-reload`

让systemd重新读取服务文件。只有新装或修改 `.service` 文件后需要执行。

### `systemctl enable --now parts-system`

这是两个操作的组合：

- `enable`：设置开机自动启动。
- `--now`：立即启动。

### `<`

把文件内容作为前面命令的输入：

```bash
mysql ... parts_database < parts_database.sql
```

表示让MySQL执行SQL文件，不是把结果保存到SQL文件。

### `>`

把命令输出写入文件：

```bash
mysqldump ... > database_backup.sql
```

表示将数据库导出内容保存为备份文件。

### `\`

Linux命令末尾的反斜杠表示“下一行仍属于同一条命令”，只是为了排版易读：

```bash
mysql \
  -u parts_database \
  -p
```

等同于写在一行。

### `&&`

前一条命令成功后才执行后一条：

```bash
command1 && command2
```

发布操作中建议初期逐行执行，更容易发现是哪一步失败。

### `$(...)`

执行括号里的命令，并把结果赋给外部命令或变量：

```bash
STAMP=$(date +%Y%m%d_%H%M%S)
```

会生成类似 `20260730_150000` 的时间字符串，用于区分每次备份。

### `$变量名`

读取之前设置的Shell变量：

```bash
echo "$BACKUP_DIR"
```

路径变量最好使用双引号包裹，避免路径中存在空格时被拆分。

---

## 八、发布前后检查清单

### 发布前

- [ ] 本地目标功能已验证。
- [ ] Python和JavaScript基础语法检查通过。
- [ ] 使用打包脚本生成部署包。
- [ ] 压缩包中没有 `.env`、`.venv` 和真实密钥。
- [ ] 已记录当前线上版本备份目录。
- [ ] 如果涉及数据库，已经完成数据库备份。

### 发布后

- [ ] `systemctl status parts-system` 为 `active (running)`。
- [ ] 服务器内部 `/api/health` 正常。
- [ ] 独立域名 `/api/health` 正常。
- [ ] 首页产品分类和产品列表可以加载。
- [ ] 产品查询、编辑、图片和供应商价格按本次改动抽查。
- [ ] `/logs` 页面正常。
- [ ] 浏览器强制刷新后静态资源为新版本。
- [ ] 保留上一版代码备份，不立即删除。

---

## 九、安全注意事项

- 不向公网开放MySQL 3306和Python 8055。
- 只有Nginx的80/443对外提供服务。
- `.env` 永远不进入部署压缩包和公开代码。
- 七牛云密钥、数据库密码出现在截图或聊天中后应及时轮换。
- 不将Python源码、`.env`、`jobs` 目录放进PHP项目的公开 `public` 目录供静态访问。
- 删除产品和执行数据库迁移前必须确认备份。
- 普通代码升级不要重新导入首次部署全量SQL。
- 线上异常时先查看 `journalctl`，不要反复重建数据库或虚拟环境。
