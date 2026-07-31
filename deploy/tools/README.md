# 部署工具

这里仅存放部署、备份和发布相关工具，与 `jobs/` 中的数据导入、数据迁移任务分开。

在项目根目录执行：

```powershell
python deploy\tools\export_deployment_database.py
python deploy\tools\build_deployment_package.py
```

- `export_deployment_database.py`：每次执行时，读取当前环境变量对应的数据库并重新生成数据库快照。已经生成的 SQL 文件不会自动同步数据库后续变化。
- `build_deployment_package.py`：每次执行时，重新扫描当前项目文件并覆盖生成部署 ZIP，因此包含执行当时已保存到磁盘的最新代码。
- 两个工具默认输出到 `deploy/artifacts/`。
- 数据导入、SPU/SKU 迁移等任务仍保留在 `jobs/`。

将SQL上传到：
/www/backup/parts_database.sql

终端导入：
/www/server/mysql/bin/mysql \
  --default-character-set=utf8mb4 \
  -u parts_database -p \
  parts_database < /www/backup/parts_database.sql

检查表：
/www/server/mysql/bin/mysql \
  -u parts_database -p \
  -D parts_database \
  -e "SHOW TABLES;"