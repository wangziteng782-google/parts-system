# parts-system Git 一键部署手册

> 创建时间：2026-08-20
> 适用场景：代码更新后一键部署到正式环境，替代旧的打包上传流程

## 一、架构概览

```text
本地开发
    ↓ git push origin master
GitHub 仓库
    ↓ git pull
服务器 /www/wwwroot/parts-system-test
    ↓ systemctl restart
systemd → Uvicorn (127.0.0.1:8055)
    ↓
Nginx 反向代理 → 独立域名
```

| 项目 | 当前值 |
|---|---|
| GitHub 仓库 | `git@github.com:wangziteng782-google/parts-system.git` |
| 默认分支 | `master` |
| 服务器项目目录 | `/www/wwwroot/parts-system-test` |
| systemd 服务名 | `parts-system` |
| Python 监听地址 | `127.0.0.1:8055` |
| 部署脚本 | `deploy/deploy.sh` |

---

## 二、首次 Git 环境搭建（只需执行一次）

### 1. 服务器生成 SSH 密钥并添加到 GitHub

```bash
ssh-keygen -t ed25519 -C "parts-system-deploy"
# 按提示保存到默认位置 /root/.ssh/id_ed25519

# 查看公钥
cat ~/.ssh/id_ed25519.pub
```

将公钥添加到 GitHub：
`GitHub → Settings → SSH and GPG keys → New SSH key`

验证连通性：

```bash
ssh -T git@github.com
# 成功显示: Hi wangziteng782-google! You've successfully authenticated...
```

### 2. 服务器 clone 项目

```bash
cd /www/wwwroot
git clone git@github.com:wangziteng782-google/parts-system.git parts-system-test
```

### 3. 配置文件保护

以下文件已通过 `.gitignore` 排除，不会被 Git 覆盖：

| 文件/目录 | 原因 |
|---|---|
| `.env` | 数据库密码、七牛云配置、JWT 密钥 |
| `.venv` | Python 虚拟环境 |
| `product_classifications.json` | 线上分类树（可能比本地新） |

---

## 三、日常部署流程

### 第 1 步：本地检查

```powershell
cd C:\wzt_WorkFile\project\parts-system
python -m compileall app.py parts_system
node --check static\js\products.js
node --check static\js\variants.js
node --check static\js\images.js
node --check static\js\logs.js
```

### 第 2 步：提交并推送

```powershell
git add -A
git commit -m "本次修改说明（如：供应商下拉改为OA搜索+自动计算四舍五入）"
git push origin master
```

### 第 3 步：服务器一键部署

```bash
cd /www/wwwroot/parts-system-test
bash deploy/deploy.sh
```

脚本自动完成以下操作（约 10-30 秒）：

| 步骤 | 操作 | 失败行为 |
|---|---|---|
| 1/5 | `git pull` 拉取最新代码 | 网络问题则中止 |
| 2/5 | `pip install` 安装新增依赖 | 依赖冲突则中止 |
| 3/5 | `compileall` 语法检查 | 语法错误则中止，**不会重启服务** |
| 4/5 | `systemctl restart` 重启服务 | — |
| 5/5 | `curl /api/health` 健康检查 | 失败则提示回滚命令 |

### 第 4 步：验证

```bash
# 服务器内部检查
curl http://127.0.0.1:8055/api/health
# 期望返回: {"status":"ok","database":"ok",...}

# 员工浏览器验证
https://<独立域名>/goods
https://<独立域名>/logs
```

> 前端静态文件更新后，员工需按 `Ctrl+F5` 强制刷新浏览器缓存。

---

## 四、部署失败回滚

### 情况 1：语法检查失败（服务未重启）

脚本在第 3 步就中止了，服务还在运行旧代码，无需回滚。

修复本地代码后重新 push：

```powershell
# 本地修复
git add -A
git commit -m "修复语法错误"
git push origin master
```

```bash
# 服务器重新部署
cd /www/wwwroot/parts-system-test
bash deploy/deploy.sh
```

### 情况 2：健康检查失败（服务已重启但异常）

```bash
cd /www/wwwroot/parts-system-test
git log --oneline -5          # 查看最近提交
git checkout <上一个commit>   # 回到上一个正常版本
systemctl restart parts-system
curl http://127.0.0.1:8055/api/health
```

确认正常后切回 master 继续开发：

```bash
git checkout master
```

### 情况 3：数据库迁移失败

如果部署包含数据库迁移且失败：

```bash
# 回滚数据库
/www/server/mysql/bin/mysql \
  --default-character-set=utf8mb4 \
  -u parts_database -p \
  parts_database < /www/backup/parts_database_before_migration.sql

# 回滚代码
cd /www/wwwroot/parts-system-test
git checkout <上一个commit>
systemctl restart parts-system
```

---

## 五、部署脚本说明

`deploy/deploy.sh` 内容：

```bash
#!/bin/bash
set -e                              # 任何步骤失败立即中止

BRANCH=${1:-master}                 # 默认 master，可传参指定分支
APP_DIR=/www/wwwroot/parts-system-test
SERVICE_NAME=parts-system
PORT=8055

# 1. git pull
# 2. pip install -r requirements.txt
# 3. compileall app.py parts_system
# 4. systemctl restart parts-system
# 5. curl /api/health 健康检查
```

如需部署其他分支（如测试分支）：

```bash
bash deploy/deploy.sh develop
```

---

## 六、发布检查清单

### 发布前

- [ ] 本地目标功能已验证
- [ ] Python 和 JavaScript 语法检查通过
- [ ] 代码已 commit 并 push 到 GitHub
- [ ] 如涉及数据库迁移，已完成数据库备份

### 发布后

- [ ] `bash deploy/deploy.sh` 输出"✅ 部署成功！"
- [ ] `systemctl status parts-system` 为 `active (running)`
- [ ] 服务器内部 `/api/health` 正常
- [ ] 独立域名 `/api/health` 正常
- [ ] 首页产品分类和产品列表可以加载
- [ ] 按本次改动抽查对应功能
- [ ] `/logs` 页面正常
- [ ] `/sales` 能同时查询"来自配件库"和"来自询价记录"的数据
- [ ] OA 询价库不可用时，`/sales` 能降级展示

---

## 七、常见问题

### Q: 部署时提示 "Permission denied (publickey)"

SSH 密钥未加载，执行：

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
```

### Q: 部署时提示 "Your local changes would be overwired by pull"

服务器上有手动修改过的文件。通常不会发生（配置文件都在 `.gitignore` 中）。如确实需要：

```bash
cd /www/wwwroot/parts-system-test
git stash        # 暂存本地改动
bash deploy/deploy.sh
git stash pop    # 恢复本地改动（谨慎操作）
```

### Q: 如何查看部署历史

```bash
cd /www/wwwroot/parts-system-test
git log --oneline -10
```

### Q: 旧的打包上传方式还能用吗？

可以。旧手册 `parts-system部署与更新手册.md` 仍保留作为备用方案。但推荐使用 Git 部署，更快更安全。
