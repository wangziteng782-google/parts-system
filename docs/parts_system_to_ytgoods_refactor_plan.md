# 配件批改系统切换到 ytgoods_ccooddee 的改造方案（讨论稿）

## 1. 结论

可以完整保留当前前端页面、弹窗、抽屉、拖拽、粘贴、图片库、规格配置和供应商价格配置等交互。

实现方式不是让前端直接理解商城数据库，而是在后端增加“兼容接口层”：

```text
现有前端
  ↓ 继续调用现有 /api/... 地址和现有JSON字段
兼容接口 / DTO
  ↓ 把页面字段翻译成商城业务模型
SPU / SPU扩展 / SKU / 规格 / 报价 / 图片 / 用户
  ↓
ytgoods_ccooddee
```

前端改动预计不超过10%，后端数据访问和业务服务约60%～75%需要重写。

当前项目有36个HTTP路由，约30个直接查询 `parts`、`product_variant_*` 或 `parts_new`，这些接口路径可以保留，但SQL和事务逻辑需要更换。

本阶段只改造和测试系统，不讨论服务器部署。

## 2. 改造原则

1. `ytgoods_ccooddee` 成为唯一业务数据库，原 `parts_database` 停止读写。
2. 前端不直接感知SPU、SKU等底层表的拆分。
3. 现有接口URL、请求格式和主要返回字段尽量保持不变。
4. 产品层使用SPU，规格组合使用SKU，供应商价格使用报价表。
5. 删除统一改为软删除，避免破坏商城已经引用的数据。
6. 所有修改记录当前 `yh_admin_user.id`。
7. 任意规格、价格、图片修改后都同步更新SPU的 `update_time`，继续支持左侧“上次修改时间”。
8. 规格、报价和图片只保留一个事实来源，避免同一价格存放多份后发生不一致。
9. 本系统的职责仍然是直接批改正式业务数据；切换到线上库后不减少编辑能力，只通过权限、事务、软删除和审计保证安全。

## 3. 页面字段兼容映射

后端详情接口继续返回当前页面认识的字段名。

### 当前线上迁移数据的特殊情况

parts迁移时采用“一条parts一条SPU”，SKU阶段又按方案B归并到规范SPU。因此当前存在：

- 全量来源SPU；
- SKU只挂在规范SPU下；
- 一部分重复SPU暂时没有SKU，但其SPU扩展原始数据仍需保留。

本批改系统不能简单使用“存在SKU”作为产品列表条件。推荐全部未删除SPU都显示，并给没有SKU的重复候选项增加“无SKU/待合并”状态，供员工继续清洗。

| 现有页面字段 | ytgoods来源/规则 |
|---|---|
| `id` | `yh_goods_spu.id` |
| `sku_code` | 兼容返回 `yh_goods_spu.spu_code`；页面标签后续可改成“产品编码” |
| `product_name` | `yh_goods_spu.goods_name` |
| `product_brand` | `yh_goods_spu.brand` |
| `model` | `yh_goods_spu.version` |
| `product_type` | `yh_goods_spu.part_id → yh_part.part_name` |
| `technical_params` | `yh_goods_spu.parameters` |
| `applicable_elevator_brand` | `yh_goods_spu.spu_ele_brand` |
| `supplier` | 当前选中SKU的当前选中报价 → `yh_supplier.supplier_name` |
| `nature` | 当前选中SKU关联的 `yh_spec_value.value` |
| `warranty` | 优先当前报价 `yh_goods_quotation.warranty`，其次SKU字段，再其次SPU扩展 |
| `substitute_model` | `yh_goods_spu_extra.substitute_model` |
| `precautions` | `yh_goods_spu_extra.precautions` 或SKU `hint` |
| `category` | `yh_goods_spu_extra.category` |
| `purchase_cost` 等采购字段 | 当前选中SKU和供应商对应的 `yh_goods_quotation` |
| `retail_price` | `yh_goods_sku_sales_price`；兼容时可同时返回报价中的销售价 |
| 其他零售、发货、报价字段 | 当前报价；原始长文本可从 `yh_goods_spu_extra` 回显 |
| `filler` / `filler_2` | `admin_id/update_id → yh_admin_user.nickname` |
| `update_time_2` | SPU、SKU、报价、图片最近修改时间中的最大值；写操作同步触发SPU更新时间 |
| 10种普通图片字段 | 按 `yh_spu_image_type.type_code` 对 `yh_goods_spu_image` 分组后组成URL数组 |
| `product_detail_images` | 从 `yh_goods_spu.detail` 提取图片URL供页面展示；保存时重新生成详情HTML |

### 重要说明

一个SPU可能有多个SKU和多个供应商，产品头部的供应商和价格不能再理解为SPU固定字段。

推荐继续使用页面现有的“选择规格与供应商”交互：

1. 默认选中第一个有效SKU。
2. 默认选中该SKU的第一条有效供应商报价。
3. 用户切换规格或供应商时，价格区随选择更新。
4. SPU基本信息始终不随规格切换。

## 4. 产品接口改造

### `GET /api/products`

- 主表从 `parts` 改为 `yh_goods_spu`。
- 关联 `yh_part` 返回三级产品分类。
- 标记对象确认前暂不返回重复标记；确认后再关联对应的SPU/SKU标记表。
- 产品名称＋型号重复检查改为 `goods_name + version`。
- 仅查询 `delete_time IS NULL`。
- 左侧更新时间使用SPU的统一业务更新时间。
- 保持当前分页、搜索、分类筛选和返回JSON不变。

### `GET /api/products/{id}`

一次组装并返回：

- SPU基本字段；
- SPU扩展字段；
- 分类名称；
- 管理员名称；
- 按类型分组的图片；
- 默认SKU/供应商的兼容价格字段。

### `POST /api/products`

保持“大弹窗先新增产品，规格以后配置”的交互：

1. 新增 `yh_goods_spu`。
2. 新增一条 `yh_goods_spu_extra`。
3. 上传或选择的图片写入 `yh_goods_spu_image`。
4. 暂时不创建SKU；首次保存规格组合时再创建。
5. `admin_id` 取当前登录用户。

### `PUT /api/products/{id}`

建立字段路由表，不能继续拼接更新单张表：

- SPU字段更新 `yh_goods_spu`；
- 原始扩展字段更新 `yh_goods_spu_extra`；
- 当前供应商价格字段更新当前 `yh_goods_quotation`；
- 零售价更新 `yh_goods_sku_sales_price`；
- 图片走专用图片接口。

前端仍提交 `{field, value}`，后端负责定位目标表。

### `DELETE /api/products/{id}`

不再物理删除，事务内软删除：

- `yh_goods_spu.delete_time`；
- 关联SKU的 `is_delete/delete_time`；
- 规格、规格值、报价、图片的 `delete_time`；
- 如果后续启用标记功能，同步关闭对应标记。

该操作应限制为有权限的管理员。

## 5. 分类树逻辑改造

当前本地 `product_classifications.json` 不再作为正式数据源。

| 页面层级 | ytgoods表 |
|---|---|
| 一级分类 | `yh_part_category` 顶级节点 |
| 二级分类 | `yh_part_category` 子节点 |
| 三级产品分类 | `yh_part` |

接口仍返回当前前端需要的：

```json
{
  "tree": [],
  "values": [],
  "counts": {},
  "unclassified_count": 0
}
```

但由SQL动态组装。

新增、编辑、删除分类都写数据库，并记录 `admin_id/update_id`。

删除改为软删除；删除已被SPU使用的三级分类时，需要先把相关SPU设为未分类或禁止删除，不能直接物理级联。

## 6. 规格配置和SKU逻辑

这是改造工作量最大的一块。

| 当前parts表 | ytgoods表 |
|---|---|
| `product_variant_specs` 中的规格名 | `yh_spec` |
| `product_variant_specs` 中的规格值 | `yh_spec_value` |
| `product_variant_group_specs` 中的组合 | `yh_goods_sku + yh_sku_spec_value` |
| `variant_group_id` | 不再使用；组合实体就是SKU ID |
| `product_variant_prices` | `yh_goods_quotation` + `yh_goods_sku_sales_price` |

### 规格名与规格值

- 每个SPU、每个规格名对应一条 `yh_spec`。
- 一个规格名下的多个值对应多条 `yh_spec_value`。
- 双击编辑规格值，直接更新原 `yh_spec_value.id`，SKU关联不丢失。
- 修改规格名只更新 `yh_spec.spec_name`，SKU和报价不受影响。
- 删除已被SKU使用的规格值时使用软删除；历史SKU仍能显示该值，并标记“已删除规格”。

### 笛卡尔积和组合列表

- 后端根据当前启用的规格值计算笛卡尔积。
- 已存在 `yh_goods_sku + yh_sku_spec_value` 的组合显示SKU及报价。
- 尚不存在SKU的组合显示“待配置”。
- 用户第一次配置供应商价格时创建对应SKU。
- 删除组合等价于软删除SKU及其当前报价，不删除规格字典。
- 新增规格名或规格值后，不修改已有SKU，不清空已有报价。
- 新组合可以按照现有交互，以第一个已配置SKU作为参考复制报价，然后员工再编辑。

### `_skuKey`

`yh_sku_spec_value` 才是SKU规格组合的事实来源。

目前导入数据每个SKU只有一个规格值，因此 `_skuKey` 保存单个 `yh_spec_value.id`。

如果以后一个SKU支持多个规格名，必须和线上项目确认 `_skuKey` 的兼容格式。建议按规格顺序保存排序后的规格值ID，例如：

```text
7383,7421,7508
```

但不能在没有确认线上读取逻辑前自行改变格式。

## 7. 供应商与价格逻辑

### 表关系

```text
SPU
  └─ SKU（一个规格组合）
       ├─ SKU规格值关联
       ├─ SKU零售价格
       └─ 多条供应商报价
            └─ 供应商
```

### 页面接口

现有 `variant-prices` 接口继续返回页面当前字段名，但后端联查：

- `yh_goods_sku`
- `yh_sku_spec_value`
- `yh_spec_value`
- `yh_goods_quotation`
- `yh_supplier`
- `yh_goods_sku_sales_price`

### 数据事实来源

推荐规则：

1. 供应商针对规格的采购报价，以 `yh_goods_quotation` 为准。
2. SKU零售价以 `yh_goods_sku_sales_price` 为准。
3. `yh_goods_sku` 中的价格字段只作为线上系统需要的默认/缓存价格。
4. 新增、修改、删除报价后，由服务层统一重新计算SKU默认价格，避免两处数据不一致。
5. 供应商输入框改为搜索 `yh_supplier`；手工输入新供应商时先创建供应商记录，再创建报价。

### 尚需确认

多供应商时，SKU主表价格应该取：

- 当前指定的默认供应商；或
- 所有有效供应商中的最低报价。

推荐使用“明确指定默认供应商”，不要静默取最低价。现有表暂时没有 `default_quotation_id`，可由业务规则或小扩展字段解决。

## 8. 图片逻辑

### 产品图片

现有11种图片交互可以完整保留，其中10种普通图片写图片明细表，商品详情图片写SPU详情HTML：

- 本地上传；
- 粘贴；
- 微信/飞书拖拽；
- 图片库选择；
- 11个类型之间拖放；
- 缩略图、排序、删除。

后端不再把URL数组写在11个字段中，而是：

- 图片类型：`yh_spu_image_type`
- 图片记录：`yh_goods_spu_image`
- 拖放图片：更新 `image_type_id` 和排序
- 封面图：同步 `yh_goods_spu.image`
- 商品详情图：解析和生成 `yh_goods_spu.detail`，不混入普通图片类型表

图片更新必须使用事务，并用 `url_hash` 防止同一SPU重复图片。

### parts_new 图片素材库

`parts_new.sql` 分析结果：

| 项目 | 数量 |
|---|---:|
| 素材产品 | 23200 |
| 有图片的素材产品 | 22483 |
| 图片引用次数 | 198813 |
| 唯一URL | 70449 |
| 重复引用 | 128364 |
| 单条最多图片 | 34 |
| JSON解析失败 | 0 |
| HTTP引用 | 82547 |
| HTTPS引用 | 116220 |

其中品牌、供应商、性质、分类等字段大部分为空，因此它应继续定位为“图片素材库”，不能作为商城SPU导入。

### 已确认方案：parts_new原表上线

已确认在线上 `ytgoods_ccooddee` 中直接建立 `parts_new` 表，保留当前表名和字段：

- `id`
- `product_name`
- `product_brand`
- `model`
- `supplier`
- `warranty`
- `applicable_elevator_brand`
- `nature`
- `category`
- `product_images`（JSON）
- `product_images` 继续保存JSON数组

建议在不改变现有字段的基础上增加分类、名称和型号查询索引。23200行、约18MB SQL对MySQL压力很小。

为了忠实保留原始素材数据，导入时不直接改写原URL。API返回给浏览器时，把 `http://soft.yitikeji.cn` 规范为HTTPS，避免部署后出现混合内容拦截。

页面选择素材图片时，只把选中的URL复制到 `yh_goods_spu_image`，素材表保持不变。

这样当前 `/api/image-library/categories` 和 `/api/image-library/products` 只需要切换数据库连接，前端交互无需改变。

### 远期可选方案：图片去重模型

如果以后要对单张图片做标签、审核、统计和失效管理，再拆分：

- 素材产品表；
- 唯一图片表（约70449行）；
- 素材产品图片关联表（约198813行）。

本轮不建议直接采用，工作量和复杂度明显更高，但当前业务收益有限。

## 9. 用户和登录

已确认本系统不提供独立登录页。应用仍可以本地直接启动，但首页和全部业务接口必须受到鉴权保护。

正式系统调用本系统暴露的进入接口并携带token：

```text
正式系统
  → GET /auth/entry?token=<短期token>
  → 本系统验证签名、有效期、签发方和受众
  → 判断是否内部用户
  → 校验 yh_admin_user 未禁用、未删除
  → 建立本系统HttpOnly会话
  → 302跳转首页 /
```

token只用于换取本系统会话，不应长期保存在URL、localStorage或前端JavaScript中。

如果正式系统给的是JWT，本系统使用约定的公钥或密钥本地验签；如果给的是不透明token，本系统调用正式系统的token校验接口。最终需由正式系统提供：

- token类型和签名算法；
- 公钥、JWKS地址或校验接口；
- 用户ID字段；
- 内部用户字段或权限字段；
- `issuer/audience/expire`规则；
- 退出登录和token失效规则。

本系统验证成功后，根据token中的用户ID关联 `yh_admin_user.id`，所有写操作使用会话用户的 `admin_id`，不能相信前端提交的员工ID。

角色权限可复用：

- `yh_sys_user_role`
- `yh_sys_role`
- `yh_sys_role_menu`

第一版权限可只判断：

```text
用户有效 + 内部用户 + 拥有parts:edit权限
```

本地开发环境可以启用显式的开发登录模式，例如 `AUTH_MODE=development` 和固定测试管理员ID，但该模式必须在生产环境强制禁用。

不建议共享正式系统Cookie，也不直接读取或验证 `yh_admin_user.password`。

## 10. 重复标记和操作审计

重复标记究竟针对SPU还是SKU尚未最终确定，因此本轮暂不建表、不迁移现有标记逻辑。

待确定后可以选择：

- SPU重复：关联 `yh_goods_spu.id`；
- SKU重复：关联 `yh_goods_sku.id`；
- 同时支持：使用 `target_type + target_id`。

系统控制台日志继续保留，但不写大体积 `app.log`。

员工修改记录可以复用 `yh_admin_log`；如果现有字段不能表达字段级旧值/新值，再单独讨论审计明细表。

## 11. 并发和数据安全

三名员工同时使用对服务器没有性能压力，但必须处理覆盖问题：

- 数据库连接改为连接池，不能每个请求执行建表或ALTER TABLE。
- 规格、SKU、报价操作使用事务和 `SELECT ... FOR UPDATE`。
- 页面保存时携带读取到的 `update_time`，后端做乐观锁检查。
- 如果别人已修改，返回409并提示刷新，不能静默覆盖。
- 分类删除、产品删除、组合删除使用软删除。
- 数据库连接、七牛密钥和SSO密钥全部使用服务器环境变量。
- 所有动态字段更新使用白名单，继续防止SQL字段注入。

## 12. 本地测试版与线上正式版

### 已确认：采用目录复制的轻量版本方式

当前由一人开发，暂不使用GitHub分支、tag和自动部署。采用：

```text
本地测试目录
  → 完成功能和测试
  → 复制为带版本号的发布目录/压缩包
  → 上传服务器新发布目录
  → 切换服务到新目录
  → 保留上一版本用于回滚
```

建议目录命名：

```text
parts-system-test/                         本地持续修改
releases/parts-system-20260728-01/         第一个发布版本
releases/parts-system-20260730-02/         第二个发布版本
releases/parts-system-20260805-03/         第三个发布版本
```

每个发布目录增加一个 `VERSION.txt`，记录版本号、日期和主要改动。

### 环境划分

| 项目 | 本地测试环境 | 线上正式环境 |
|---|---|---|
| `APP_ENV` | `development` / `test` | `production` |
| 代码 | 本地测试目录 | 带版本号的发布副本 |
| 数据库 | `ytgoods_ccooddee_test` | `ytgoods_ccooddee` |
| 登录 | 开发测试用户或测试token | 正式系统token |
| Cookie Secure | 可关闭（仅localhost） | 必须开启 |
| Debug/reload | 可开启 | 必须关闭 |
| 七牛 | 测试目录或测试bucket | 正式bucket |

本地测试版不能直接把正式库当测试库。读查询可以临时连接正式只读账号，但新增、修改、删除测试必须使用测试数据库。

推荐从正式库定期脱敏复制结构和必要样本到 `ytgoods_ccooddee_test`，而不是维护两套不同表结构。

### 配置管理

使用服务器环境变量或不入库的环境文件：

```text
APP_ENV
DB_HOST
DB_PORT
DB_NAME
DB_USER
DB_PASSWORD
AUTH_MODE
AUTH_ISSUER
AUTH_AUDIENCE
AUTH_PUBLIC_KEY / AUTH_JWKS_URL / AUTH_INTROSPECTION_URL
SESSION_SECRET
QINIU_ACCESS_KEY
QINIU_SECRET_KEY
QINIU_BUCKET
QINIU_DOMAIN
```

复制发布包时排除：

```text
.env
.env.*
!.env.example
*.local.json
uploads/
jobs/*_state.json
jobs/*_errors.jsonl
```

正式服务器的 `.env`、数据库密码、token密钥和七牛密钥独立保存在服务器共享配置目录，不随代码目录一起复制覆盖。

### 数据库版本

数据库结构也必须版本化，不能继续在每个请求里自动 `CREATE TABLE` 或 `ALTER TABLE`。

建议：

```text
sql/migrations/
  V001__baseline_checks.sql
  V002__create_parts_new.sql
  V003__add_query_indexes.sql
  V004__future_cleanup_mark.sql
```

增加一张轻量 `schema_migrations` 表记录已执行版本，或者后续引入Alembic。每个正式版本在部署应用前执行对应迁移。

数据库迁移遵循：

1. 先备份；
2. 优先做向后兼容的新增；
3. 新旧代码短时间都能运行；
4. 验证新版本后再清理旧字段或旧逻辑；
5. 每个迁移脚本只执行一次，并有检查和回滚说明。

### 发布与回滚

正式发布流程：

1. 本地测试库回归；
2. 停止继续修改本地测试目录；
3. 复制为带日期和序号的发布目录；
4. 备份正式库；
5. 执行数据库迁移；
6. 把发布目录上传到服务器的新版本目录；
7. 健康检查和核心接口冒烟测试；
8. 切换服务的当前目录并重启。

代码回滚时把服务切回上一个保留的发布目录。数据库迁移尽量采用向后兼容设计，避免因为代码回滚必须立即反向修改大量业务数据。

静态文件可在URL附带应用版本或内容hash，避免浏览器继续缓存旧JS。

### GitHub部署作为未来可选方案（当前不采用）

以后多人开发或发布频繁时，可以再切换到GitHub私有仓库和发布tag；当前目录复制方案不依赖GitHub。

未来GitHub方式为：

```text
本地开发电脑
  → Git提交
  → 推送GitHub私有仓库
  → main打发布tag
  → 服务器按tag拉取
  → 安装依赖/执行迁移
  → 重启应用
```

服务器第一次部署：

```bash
git clone <private-repository-url> /opt/parts-system
cd /opt/parts-system
git fetch --tags
git checkout v1.0.0

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

服务器的 `.env`、数据库密码、token公钥和七牛密钥单独配置，不从GitHub下载。

后续发布：

```bash
cd /opt/parts-system
git fetch --tags
git checkout v1.1.0
.venv/bin/pip install -r requirements.txt
# 执行该版本数据库迁移
sudo systemctl restart parts-system
```

回滚：

```bash
cd /opt/parts-system
git checkout v1.0.0
sudo systemctl restart parts-system
```

生产服务器建议：

```text
正式系统/浏览器
  → HTTPS
  → Nginx
  → 127.0.0.1:8055 Uvicorn
  → ytgoods_ccooddee
```

Uvicorn由 `systemd` 管理，不能依赖SSH窗口长期运行。Nginx负责域名、HTTPS、上传大小和反向代理。

私有GitHub仓库在服务器上可以使用只读Deploy Key，服务器只允许拉取代码，不允许向仓库推送。

当前阶段无需配置Deploy Key、GitHub Actions或自动部署。

如果服务器无法访问GitHub，可以由GitHub Actions构建发布压缩包，再通过SCP上传服务器，但仍应使用带版本号的发布包，不能手工下载无版本ZIP覆盖。

## 13. 代码结构调整

建议保留现有路由和前端，增加清晰的数据层：

```text
parts_system/
  db.py
  auth.py
  dependencies.py
  repositories/
    spu_repository.py
    catalog_repository.py
    spec_repository.py
    quotation_repository.py
    image_repository.py
    material_repository.py
  services/
    product_service.py
    variant_service.py
    image_service.py
  schemas/
    product_compat.py
    variant_compat.py
  routes/
    products.py
    catalog.py
    variants.py
    image_library.py
```

现有 `shared.py` 中的自动建表、自动ALTER和硬编码本地数据库配置要移除。

### 后端技术选型（已确定）

采用以下组合：

- FastAPI：保留现有Web框架和接口路径；
- SQLAlchemy 2.x：统一数据库映射、查询、连接池和事务；
- PyMySQL：继续作为MySQL同步驱动；
- Alembic：管理以后新增字段、索引和表结构版本；
- Pydantic：校验请求参数，并通过兼容DTO保持当前前端JSON格式不变。

本系统当前并发人数较少，数据库和现有驱动都是同步方式，因此暂不使用
`AsyncSession`、`asyncmy` 或 `aiomysql`。数据库接口使用FastAPI的同步
`def` 路由和“每个请求一个Session”；七牛上传等外部网络操作可以根据需要
单独采用异步方式。这样不会在异步事件循环中执行同步数据库IO，也减少线上
驱动、事务和连接池问题。

数据调用方向固定为：

```text
routes（HTTP、参数、响应）
  → services（业务规则、权限、事务边界）
  → repositories（查询和持久化）
  → SQLAlchemy models
  → ytgoods_ccooddee
```

分层约束：

- 路由层不直接拼SQL，也不承载规格组合、报价等业务规则；
- 服务层控制完整业务操作的提交和回滚；
- 仓储层只负责查询、增加、修改和删除，不自行随意 `commit`；
- 每个请求创建独立Session，请求结束必须关闭，禁止全局共享Session；
- 普通CRUD和关联关系使用ORM，复杂统计或批量语句允许使用SQLAlchemy Core；
- 所有条件值必须参数化，动态排序字段、表名和列名必须经过白名单；
- 对线上已有表只做映射，不运行 `Base.metadata.create_all()`；
- Alembic先建立当前线上结构的基线，之后只执行明确、可回滚或向后兼容的迁移；
- 数据库账号、密码、连接池参数全部来自环境变量。

建议连接池初始值为 `pool_size=5`、`max_overflow=5`、
`pool_pre_ping=True`、`pool_recycle=1800`。上线后再根据MySQL
`wait_timeout`、实际请求耗时和连接数监控调整。

SQLAlchemy提升的是参数绑定、事务一致性、连接回收和代码可维护性，并不会自动
解决全部安全问题。鉴权、数据权限、请求校验、上传校验、软删除、并发修改保护和
数据库最小权限仍由服务层及部署配置负责。

现有接口迁移不采用一次性重写：先映射线上表并替换只读接口，再逐个替换写接口，
每替换一组都执行旧接口JSON契约对比，最后才删除旧的PyMySQL直连和自动DDL代码。

## 14. 文件和接口改造量

当前规模：

| 部分 | 行数 |
|---|---:|
| Python后端 | 2262 |
| 前端JavaScript | 3413 |
| CSS | 1797 |
| HTML模板 | 131 |
| HTTP路由 | 36 |

预计：

- 后端现有代码修改或替换约1300～1800行；
- 新增仓储、服务、鉴权和兼容DTO约1200～1800行；
- 前端只调整鉴权、并发冲突和少量字段语义，约100～300行；
- CSS和主要HTML布局基本不动；
- 约30个接口需要数据库实现替换；
- 在线上导入原 `parts_new` 表；
- 清理标记表是否新增，等待确认标记对象；
- 可能增加少量索引，不新增parts兼容主表。

## 15. 人工工作量估算

不包含服务器部署：

| 阶段 | 预计工作量 |
|---|---:|
| 数据库配置、连接池、兼容DTO、登录骨架 | 2～4人日 |
| 产品列表、详情、新增、编辑、软删除 | 4～6人日 |
| 分类树、供应商 | 2～3人日 |
| 规格、笛卡尔组合、SKU生命周期 | 5～8人日 |
| 供应商报价、零售价和默认价格同步 | 3～5人日 |
| 产品图片、上传、拖放、详情图 | 3～5人日 |
| parts_new导入和图片素材库 | 2～3人日 |
| 用户权限、并发、回归测试和数据核对 | 4～6人日 |
| 合计（标记功能另计） | 24～40人日 |

如果先做“能用的第一版”，暂缓复杂角色权限、字段级审计和多规格 `_skuKey` 兼容，约18～25人日。

## 16. 推荐实施顺序

1. 冻结当前前端接口JSON，保存接口样例作为契约测试。
2. 新建ytgoods数据访问层和兼容DTO。
3. 先改只读：分类树、产品列表、产品详情。
4. 改产品字段编辑、新增和软删除。
5. 改产品图片和图片素材库。
6. 改规格名、规格值和组合列表。
7. 改SKU创建、删除和供应商报价。
8. 接入用户SSO和权限。
9. 做双库只读结果对比和前端全流程回归。
10. 验收后关闭parts数据库连接。
11. 全部需求完成后再部署服务器。

## 17. 仍需最终确认的业务规则

1. 产品列表显示全部未删除SPU，还是只显示已经有SKU的规范SPU？
   - 推荐：显示全部未删除SPU，因为本系统承担数据清洗。
2. 一个SKU包含多个规格值时，线上 `_skuKey` 要求什么格式？
   - 必须向线上项目确认；关系真相仍以 `yh_sku_spec_value` 为准。
3. 多供应商报价时，SKU主表默认价格取指定供应商还是最低价？
   - 推荐：指定默认供应商。
4. 删除产品、分类、SKU是否全部采用软删除？
   - 推荐：全部软删除。
5. 正式系统token的具体契约是什么？
   - 已确认通过token进入；仍需确认JWT/不透明token、签名方式、用户ID、内部用户和权限字段。
6. 重复/待删除标记最终针对SPU、SKU还是两者？
   - 用户确认后再设计表，不提前实现。
