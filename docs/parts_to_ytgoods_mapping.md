# parts → ytgoods 字段及规格关系（当前执行方案）

## 数据来源

- 当前迁移源文件：`C:\Users\yiti\Desktop\parts.sql`
- SQL导出时间：2026-07-28 10:42:57
- 数据行数：5304
- ID范围：1～5326（中间允许缺号）
- 字段数：46
- 迁移脚本直接解析SQL快照，不再读取运行中的 `parts_database.parts`。
- 状态文件保存SQL的SHA256；SQL内容变化且已有迁移记录时，脚本会停止，避免相同 `parts.id` 错误更新旧SPU。

## 一、迁移边界

- `parts` 每一行生成一条 `yh_goods_spu`，本阶段不按名称、品牌、型号去重。
- 不修改 `yh_goods_spu` 原始字段。
- 已新增 `yh_goods_spu_extra`，按 `spu_id` 一对一保存 SPU 主表无法容纳的原始业务字段。
- 本阶段不写 `yh_goods_quotation`。
- `supplier` 先匹配或新增 `yh_supplier`，再把 `yh_supplier.id` 写入 `yh_goods_spu_extra.supplier_id`。
- 采购价格、零售价格、发票、运费、质保、发货等字段原样写入 `yh_goods_spu_extra`，不写 `yh_goods_quotation`。
- `product_type` 先匹配 `yh_part.part_name`，再把 `yh_part.id` 写入 `yh_goods_spu.part_id`。

## 二、parts 全部字段对应总表

以下按 `parts` 当前实际字段顺序列出，共 46 个字段。

| 序号 | parts 字段 | 中文含义 | ytgoods 对应表.字段 | 本轮处理 |
|---:|---|---|---|---|
| 1 | `id` | parts 主键 | 无目标字段 | 不写入数据库，仅作为迁移定位键保存在本地状态中 |
| 2 | `sku_code` | SKU编码 | `yh_goods_spu.spu_code` | parts 本轮等同 SPU，因此原编码作为 SPU 编码；为空时生成唯一 SPU 编码 |
| 3 | `product_name` | 产品名称 | `yh_goods_spu.goods_name` | 直接写入 |
| 4 | `product_brand` | 产品品牌 | `yh_goods_spu.brand` | 直接写入 |
| 5 | `model` | 型号 | `yh_goods_spu.version` | 直接写入 |
| 6 | `supplier` | 供应商 | `yh_supplier.supplier_name`；`yh_goods_spu_extra.supplier_id` | 按名称匹配或新增供应商，再用 `supplier_id` 建立当前 SPU 与供应商的关系 |
| 7 | `warranty` | 质保 | 当前：`yh_goods_spu_extra.warranty`；后续：`yh_goods_sku.warranty` | 质保是独立字段，不属于规格；先完整保存在扩展表，生成 SKU 时再同步 |
| 8 | `applicable_elevator_brand` | 适用电梯品牌 | `yh_goods_spu.spu_ele_brand` | 直接写入 |
| 9 | `nature` | 性质 | `yh_spec.spec_name` 固定“默认”；`yh_spec_value.value` 写性质原值 | 本轮生成默认规格定义与规格值，例如“默认 → 全新” |
| 10 | `substitute_model` | 替代型号 | `yh_goods_spu_extra.substitute_model` | 原样保存，不再合并进描述 |
| 11 | `precautions` | 注意事项 | `yh_goods_spu_extra.precautions` | 原样保存 |
| 12 | `category` | 品类归属 | `yh_goods_spu_extra.category` | 保存旧品类；商城正式分类仍使用 `product_type` |
| 13 | `technical_params` | 技术参数 | `yh_goods_spu.parameters` | 保持原多行文本写入 |
| 14 | `purchase_cost` | 采购成本价 | `yh_goods_spu_extra.purchase_cost` | 按原 `varchar(100)` 文本保存，不强制转数值 |
| 15 | `purchase_special_invoice` | 进项专票 | `yh_goods_spu_extra.purchase_special_invoice` | 原样保存 |
| 16 | `purchase_general_invoice` | 进项普票 | `yh_goods_spu_extra.purchase_general_invoice` | 原样保存 |
| 17 | `purchase_shipping` | 采购运费 | `yh_goods_spu_extra.purchase_shipping` | 原样保存 |
| 18 | `retail_price` | 零售价格 | `yh_goods_spu_extra.retail_price` | 按原文本保存 |
| 19 | `retail_ladder_price` | 零售阶梯价 | `yh_goods_spu_extra.retail_ladder_price` | 原样保存 |
| 20 | `retail_tax` | 零售税费 | `yh_goods_spu_extra.retail_tax` | 原样保存 |
| 21 | `retail_shipping` | 零售运费 | `yh_goods_spu_extra.retail_shipping` | 原样保存 |
| 22 | `remark` | 备注 | `yh_goods_spu_extra.remark` | 原样保存 |
| 23 | `daily_cutoff_time` | 每日截单时间 | `yh_goods_spu_extra.daily_cutoff_time` | 原样保存 |
| 24 | `quote_validity` | 报价有效期 | `yh_goods_spu_extra.quote_validity` | 原样保存 |
| 25 | `shipping_origin` | 发货地 | `yh_goods_spu_extra.shipping_origin` | 原样保存 |
| 26 | `shipping_time` | 发货时间 | `yh_goods_spu_extra.shipping_time` | 原样保存 |
| 27 | `remark_2` | 备注(2) | `yh_goods_spu_extra.remark_2` | 独立保存，不与 `remark` 合并，避免信息丢失 |
| 28 | `updater` | 更新人 | 无 | `yh_goods_spu` 没有更新人字段；不写入 |
| 29 | `key_part_images` | 关键部位图片 | `yh_goods_spu_image`，类型来自 `yh_spu_image_type` | 每个链接拆成一条图片记录；第一张有效普通图片还可作为 `yh_goods_spu.image` |
| 30 | `actual_photos` | 实物图照片 | `yh_goods_spu_image`，类型来自 `yh_spu_image_type` | 每个链接拆成一条图片记录 |
| 31 | `product_image_3` | 商品图片3 | `yh_goods_spu_image`，类型来自 `yh_spu_image_type` | 每个链接拆成一条图片记录 |
| 32 | `product_image_4` | 商品图片4 | `yh_goods_spu_image`，类型来自 `yh_spu_image_type` | 每个链接拆成一条图片记录 |
| 33 | `product_image_5` | 商品图片5 | `yh_goods_spu_image`，类型来自 `yh_spu_image_type` | 每个链接拆成一条图片记录 |
| 34 | `product_image_6` | 商品图片6 | `yh_goods_spu_image`，类型来自 `yh_spu_image_type` | 每个链接拆成一条图片记录 |
| 35 | `product_image_7` | 商品图片7 | `yh_goods_spu_image`，类型来自 `yh_spu_image_type` | 每个链接拆成一条图片记录 |
| 36 | `product_image_8` | 商品图片8 | `yh_goods_spu_image`，类型来自 `yh_spu_image_type` | 每个链接拆成一条图片记录 |
| 37 | `product_image_9` | 商品图片9 | `yh_goods_spu_image`，类型来自 `yh_spu_image_type` | 每个链接拆成一条图片记录 |
| 38 | `product_image_10` | 商品图片10 | `yh_goods_spu_image`，类型来自 `yh_spu_image_type` | 每个链接拆成一条图片记录 |
| 39 | `product_detail_images` | 商品详情图片 | `yh_goods_spu.detail` | 转成图片 HTML；不写普通图片关系表 |
| 40 | `filler` | 填报人 | `yh_admin_user.id → yh_goods_spu.admin_id` | 只保留这一套人员字段；按 username/nickname 匹配管理员 ID |
| 41 | `update_time` | 更新时间 | `yh_goods_spu.create_time` / `update_time` | 与 `update_time_2` 比较；较早值作为创建时间，较晚值作为更新时间 |
| 42 | `filler_2` | 填报人(2) | 无 | 目标 SPU 只有一个 `admin_id`，本轮不写第二套填报人 |
| 43 | `update_time_2` | 更新时间(2) | `yh_goods_spu.create_time` / `update_time` | 与 `update_time` 比较；较早值作为创建时间，较晚值作为更新时间 |
| 44 | `filler_ip` | 填报IP | 无 | 商城无对应业务字段，本轮不写 |
| 45 | `product_type` | 产品分类 | `yh_part.part_name → yh_part.id → yh_goods_spu.part_id` | 按三级部件名称匹配；匹配不到时停止该条迁移并记录错误 |
| 46 | `variant_groups_initialized` | 规格组合初始化状态 | 无 | parts 系统内部状态，本轮不写 |

### ytgoods 自动/固定字段

| ytgoods 字段 | 取值规则 |
|---|---|
| `yh_goods_spu.unit_id` | 使用 `yh_unit` 中约定的默认单位 ID |
| `yh_goods_spu.status` | 写 `1`，即上架 |
| `yh_goods_spu.delete_time` | `NULL` |
| `yh_goods_spu.image` | 按关键部位图片、实物图、商品图片3～10的顺序取第一张有效图片 |
| `yh_spec.spec_code` | 脚本为每个 SPU 的默认规格生成唯一编码 |
| `yh_spec.status` | `1` |
| `yh_spec.sort_order` | `0` |
| `yh_spec_value.extra_price` | `NULL`，不迁移价格 |

## 三、已新增的 SPU 扩展表

表名建议：`yh_goods_spu_extra`。

用途：

- 一条 SPU 对应一条扩展记录，通过 `spu_id` 一对一关联。
- `supplier_id` 关联现有 `yh_supplier.id`。
- 原样保存 SPU 主表无法容纳的旧系统字段。
- 不使用 `yh_goods_quotation`。
- 不增加 `source_part_id`、`source_field`。

### 建表 SQL（已执行）

```sql
CREATE TABLE `yh_goods_spu_extra` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT 'SPU扩展数据主键',
  `spu_id` int(11) UNSIGNED NOT NULL COMMENT '关联yh_goods_spu.id',
  `supplier_id` bigint(20) DEFAULT NULL COMMENT '关联yh_supplier.id',
  `warranty` varchar(100) DEFAULT NULL COMMENT '质保',
  `substitute_model` varchar(500) DEFAULT NULL COMMENT '替代型号',
  `precautions` varchar(500) DEFAULT NULL COMMENT '注意事项',
  `category` varchar(100) DEFAULT NULL COMMENT '原品类归属',
  `purchase_cost` varchar(100) DEFAULT NULL COMMENT '采购成本价',
  `purchase_special_invoice` varchar(100) DEFAULT NULL COMMENT '进项专票',
  `purchase_general_invoice` varchar(100) DEFAULT NULL COMMENT '进项普票',
  `purchase_shipping` varchar(100) DEFAULT NULL COMMENT '采购运费',
  `retail_price` varchar(100) DEFAULT NULL COMMENT '零售价格',
  `retail_ladder_price` varchar(100) DEFAULT NULL COMMENT '零售阶梯价',
  `retail_tax` varchar(100) DEFAULT NULL COMMENT '零售税费',
  `retail_shipping` varchar(100) DEFAULT NULL COMMENT '零售运费',
  `remark` varchar(100) DEFAULT NULL COMMENT '备注',
  `remark_2` varchar(100) DEFAULT NULL COMMENT '备注2',
  `daily_cutoff_time` varchar(500) DEFAULT NULL COMMENT '每日截单时间',
  `quote_validity` varchar(100) DEFAULT NULL COMMENT '报价有效期',
  `shipping_origin` varchar(100) DEFAULT NULL COMMENT '发货地',
  `shipping_time` varchar(500) DEFAULT NULL COMMENT '发货时间',
  `admin_id` int(11) DEFAULT NULL COMMENT '创建管理员ID，对应yh_admin_user.id',
  `delete_time` timestamp NULL DEFAULT NULL COMMENT '删除时间',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_goods_spu_extra_spu` (`spu_id`),
  KEY `idx_goods_spu_extra_supplier` (`supplier_id`),
  KEY `idx_goods_spu_extra_admin` (`admin_id`),
  CONSTRAINT `fk_goods_spu_extra_spu`
    FOREIGN KEY (`spu_id`) REFERENCES `yh_goods_spu` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_goods_spu_extra_supplier`
    FOREIGN KEY (`supplier_id`) REFERENCES `yh_supplier` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='SPU原系统扩展业务数据';
```

价格和发票字段继续使用 `varchar`，与 `parts` 类型保持一致。这样可以完整保留数字、`含税`、`不含`、`协商`、`面议` 等混合内容，不在迁移阶段强制转换。

### 供应商处理关系

```text
parts.supplier
    ↓ 按 supplier_name 精确匹配
yh_supplier.id
    ↓
yh_goods_spu_extra.supplier_id
```

- 找到同名有效供应商：复用原 `yh_supplier.id`。
- 找不到：在 `yh_supplier` 新增供应商主数据，再记录其 ID。
- `supplier` 为空：`supplier_id = NULL`。
- 不创建 `yh_goods_quotation`。

新建供应商时的字段规则：

| `yh_supplier` 字段 | 来源/取值 |
|---|---|
| `id` | 数据库自增 |
| `supplier_code` | 脚本生成唯一编码，如 `GY-PARTS-哈希值` |
| `supplier_name` | `parts.supplier` |
| `contact_person` | `NULL`，parts 无对应字段 |
| `contact_phone` | `NULL`，parts 无对应字段 |
| `province` | `NULL`；`shipping_origin` 是该产品的发货地，不能直接当成供应商省份 |
| `city` | `NULL` |
| `area` | `NULL` |
| `address` | `NULL` |
| `cooperation_status` | `1` |
| `remark` | `NULL`；parts 的商品备注写扩展表，不覆盖供应商备注 |
| `admin_id` | 由 `parts.filler` 匹配 `yh_admin_user.id` |
| `delete_time` | `NULL` |
| `create_time` | 本条 SPU 的创建时间 |
| `update_time` | 本条 SPU 的更新时间 |

## 四、parts 性质对应商城规格

每个 SPU 只建立一个统一规格，规格名称固定为“默认”，`parts.nature` 作为该规格的规格值。

| parts 字段 | `yh_spec.spec_name` | `yh_spec_value.value` | 备注 |
|---|---|---|---|
| `nature` | 默认 | parts 原值，如“全新”“二手” | 规格名称不使用“性质”，统一使用“默认” |

`nature` 为空、`-`、`NULL` 时，不生成该 SPU 的默认规格值。

以下字段不属于规格：

- `warranty`：质保先写 `yh_goods_spu_extra.warranty`，后续生成 SKU 时同步到 `yh_goods_sku.warranty`。
- `substitute_model`：替代型号写 `yh_goods_spu_extra.substitute_model`。
- `category`：旧品类写 `yh_goods_spu_extra.category`；正式分类仍使用 `product_type → yh_part.id → yh_goods_spu.part_id`。

## 五、规格三表之间的写入关系

以 `parts.nature = 全新` 为例：

### 1. `yh_spec`：规格定义

| 目标字段 | 来源/规则 |
|---|---|
| `spu_id` | 本条 parts 新生成的 `yh_goods_spu.id` |
| `spec_code` | 脚本生成该 SPU 内唯一编码 |
| `spec_name` | 固定写“默认” |
| `unit_id` | `NULL` |
| `param_type` | “枚举” |
| `status` | `1` |
| `sort_order` | `0` |
| `admin_id` | 与 SPU 相同的管理员 ID |

### 2. `yh_spec_value`：规格值

| 目标字段 | 来源/规则 |
|---|---|
| `spec_id` | 上一步生成的 `yh_spec.id` |
| `value` | “全新” |
| `extra_price` | `NULL`，本阶段不迁移价格 |
| `admin_id` | 与 SPU 相同的管理员 ID |

### 3. `yh_sku_spec_value`：SKU 与规格值关系

| 目标字段 | 来源/规则 |
|---|---|
| `sku_id` | 必须来自 `yh_goods_sku.id` |
| `value_id` | 上一步生成的 `yh_spec_value.id` |

当前阶段只生成 SPU、不生成 SKU 时，`yh_sku_spec_value` **不能写入**，因为它的 `sku_id` 为必填字段。  
以后生成 SKU 时，再为该 SKU 写入其选中的所有 `value_id`。如果现在就要求写第三张表，则必须同时生成一条默认 `yh_goods_sku`，这已经超出“只导 SPU”的范围，需要另行确认。

质保不进入上述三张规格表。当前保存在扩展表，创建 SKU 时再同步：

| parts 字段 | 当前目标字段 | 后续 SKU 目标字段 |
|---|---|---|
| `warranty` | `yh_goods_spu_extra.warranty` | `yh_goods_sku.warranty` |

## 六、图片关系

| parts 字段 | 目标 |
|---|---|
| `key_part_images` | 已有 `yh_spu_image_type` 中“关键部位图片”类型 + `yh_goods_spu_image` |
| `actual_photos` | “实物图照片”类型 + `yh_goods_spu_image` |
| `product_image_3`～`product_image_10` | 各自图片类型 + `yh_goods_spu_image` |
| `product_detail_images` | 不写图片类型表，写 `yh_goods_spu.detail` |

不写 `source_part_id`、`source_field`，不再新增任何图片表。

## 七、仍然不写入的内部字段

| parts 字段 | 原因 |
|---|---|
| `id` | 不写目标业务表，仅作为本地迁移定位键 |
| `updater` | 目标 SPU 没有更新人字段 |
| `filler_2` | 目标 SPU 只保留一个创建管理员 |
| `filler_ip` | ytgoods 无对应业务字段 |
| `variant_groups_initialized` | parts 系统内部状态，ytgoods 无对应业务字段 |

## 八、填报人对应 `yh_admin_user`

`yh_goods_spu` 只有一个 `admin_id`，不能同时保存 `filler`、`filler_2`、`updater` 三个人员字段。

建议只使用 `parts.filler` 作为创建人，按去除空格后的用户名或昵称匹配 `yh_admin_user.id`；`filler_2` 和 `updater` 不再写入 SPU。

已确认的人员关系：

| parts 人员名称 | `yh_admin_user.id` | 匹配依据 |
|---|---:|---|
| admin | 1 | username=admin |
| 李文乐 | 22 | 业务别名对应 username/nickname=lwl |
| 苏稳 | 43 | nickname=苏稳 |
| 曹向荣 | 45 | nickname=曹向荣（目标值末尾有空格，规范化后匹配） |
| 马佳畅 | 46 | nickname=马佳畅 |
| 李珊珊 | 47 | nickname=李珊珊 |
| 王梦媛 | 48 | nickname=王梦媛 |
| 杨薇 | 49 | nickname=杨薇 |

以下来源值目前无法匹配有效管理员，不能擅自对应：

- `t1`
- `李`

对无法匹配的创建人，建议让 `yh_goods_spu.admin_id` 保持 `NULL` 并输出迁移错误清单，不自动归到超级管理员。
