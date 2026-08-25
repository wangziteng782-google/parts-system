# parts-system 项目长期记忆

## 项目定位
「电梯配件管理系统」—— 采购端 + 销售端的配件批改/报价系统。FastAPI + Jinja2 模板 + MySQL + 七牛云图片存储。

## 技术架构
- 后端：FastAPI（Python 3.11，独立 venv），Uvicorn 监听 `127.0.0.1:8055`，Nginx 反代。
- 前端：Jinja2 模板 + `static/` 下的原生 CSS/JS（无前端框架）。
- 数据库：MySQL，主库 `parts_database`，另连 OA 库 `oa_yixiuti`（查供应商/税率）。
- 配置：`.env`（dotenv）+ `qiniu_config.local.json` + `migration_target.local.json` + `product_classifications.json`。
- 代码结构（已从早期单文件 app.py 重构为包结构）：
  - `parts_system/application.py` 入口，注册各路由模块。
  - `parts_system/routes/`：products / sales / variants / catalog / inquiries / logs / feedback / image_library / pages / health / legacy_params。
  - `parts_system/model/`：database.py（连接 + 惰性迁移）、migration.py（建表/加列）。
  - `parts_system/config/constants.py`：DB 配置、七牛、产品分类树、字段映射。
  - `parts_system/auth.py` 鉴权中间件。
- 启动方式：`python -m uvicorn parts_system.application:app --host 127.0.0.1 --port 8055`（或旧 `app.py` 入口，需确认 deploy 配置）。

## 核心业务概念
- **产品分类树**：机房/轿厢/井道/底坑/厅轿门/其他机械/电子/扶梯/对讲 等大类，三级结构（大类→类→具体配件名）。
- **价格体系**：采购成本价、进项专票/普票、采购运费、零售价、零售阶梯价、零售税费/运费。
- **供应商**：主库 parts 表 + `product_variant_prices` 表（产品变体价格，含 supplier 字段），供应商也可能来自 OA 库查询。
- **采购端/销售端**两套界面，销售端 sales.html + sales.js/css。
- 图片字段多达 10+ 个（key_part_images、actual_photos、product_image_3~10、detail_images），走七牛云。

## Git 分支
- 当前开发分支：**AItest**（另：dev、master）。
- 近期工作集中在 sales 模块（销售端）与图片上传、供应商双层配置。

## 用户协作偏好
- 中文沟通，偏好简洁、克制、直接执行的回复风格。
- UI 调整偏好逐元素精确控制（如字号精确到 px）。
- 常用飞书（feishu）云文档协作；飞书 App ID cli_aafbdf4db9f8dbda（Hermes 集成，strict_mode off）。
- 会并行推进多个任务（本项目 Web 功能 + 优氙费控培训文档）。

## 常用路径
- 项目根：`C:\wzt_WorkFile\project\parts-system`
- 静态资源：`static/`（css/js 分 7+7 个文件）
- 模板：`templates/`（4 个 html）
