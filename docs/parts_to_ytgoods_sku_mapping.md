# parts → ytgoods SKU 迁移方案（方案B已确认）

## 一、线上数据库现状

只读检查 `ytgoods_ccooddee` 后确认：

- `yh_goods_sku`：当前没有正式数据。
- `yh_sku_spec_value`：当前没有数据。
- `yh_goods_sku_sales_price`：当前没有数据。
- `yh_price_type`：当前没有价格类型。
- `yh_goods_quotation`：当前没有有效报价数据。
- 当前已生成的 `yh_spec` 都是“默认”规格，这是正在执行的 SPU 迁移产生的数据。

数据库结构表达的关系为：

```text
yh_goods_spu
  ├─ version（型号）
  ├─ yh_spec（规格名称：默认）
  │    └─ yh_spec_value（规格值：parts.nature）
  └─ yh_goods_sku
       ├─ yh_sku_spec_value → yh_spec_value
       ├─ price / special_price / normal_price
       ├─ yh_goods_sku_sales_price → yh_price_type
       └─ yh_goods_quotation → yh_supplier
```

因此数据库实际不是把价格作为SKU的固定唯一关系，而是：

```text
SPU型号 + 规格值 → SKU
价格 → SKU的可修改业务数据
```

为了避免首次迁移时把旧数据中“同型号、同性质、不同零售价”的记录错误合并，首次迁移去重键可以临时加入零售价。迁移完成后，价格正常修改不再新建SKU。

## 二、基于 parts.sql 的数据测算

数据源：

```text
C:\Users\yiti\Desktop\parts.sql
```

总计5304条。

推荐分组规则测算：

| 项目 | 数量 |
|---|---:|
| 原parts记录 | 5304 |
| 规范化后SPU | 约4709 |
| 按“SPU + 性质 + 初始零售价”生成的SKU | 约5061 |
| 可以合并的重复来源行 | 243 |
| 一个SKU对应多个供应商的情况 | 120 |
| 一个SPU存在多个SKU的情况 | 约319 |
| 单个SPU最多SKU数量 | 5 |
| 型号为空 | 17 |
| 性质为空 | 635 |
| 零售价为空 | 1682 |
| 来源SKU编码非空 | 80 |
| 来源SKU编码唯一值 | 71 |

## 三、推荐的SPU分组规则

SPU代表相同产品型号，使用以下规范化字段分组：

```text
产品分类 product_type
+ 产品名称 product_name
+ 产品品牌 product_brand
+ 型号 model
```

处理规则：

- 去除首尾空格、连续空格，英文统一小写后比较。
- `model`为空的17条记录不互相合并，使用 `parts.id` 作为临时分组补充键。
- `applicable_elevator_brand` 不作为SPU唯一键；同组出现多个适用品牌时去重合并。
- `product_type` 继续匹配 `yh_part.part_name`，写入 `yh_goods_spu.part_id`。

## 四、推荐的SKU去重规则

首次迁移SKU键：

```text
SPU分组键
+ 规格值 nature
+ 初始零售价 retail_price
```

空值规则：

- `nature`为空时，规格值使用“默认”。
- `retail_price`为空时，去重键使用内部标记“待定价”，但数据库价格字段不写假价格。
- 初始零售价只用于迁移阶段避免错误合并，后续调价直接更新SKU价格，不新建SKU。
- 供应商不属于SKU唯一键；同一SKU可以拥有多条供应商报价。

如果完全不把价格加入迁移去重键，则约生成4976个SKU，但有64组同规格数据存在不同零售价，需要人工决定保留哪个价格。因此首次迁移建议采用较保守的5061个SKU方案。

## 五、SKU编码规则

`parts.sku_code` 只有80条非空、71个唯一值，不能直接作为所有SKU编码。

建议：

1. 来源SKU编码非空且全局唯一：优先保留。
2. 来源编码重复：不直接复用。
3. 无编码或重复时，按SKU规范化键生成确定性编码：

```text
SKU-P-<SKU规范化键SHA1前12位>
```

例如：

```text
SKU-P-A12B34C56D78
```

同一份SQL重复执行时生成相同编码。建议正式迁移前给 `yh_goods_sku.sku_code` 增加唯一索引。

## 六、规格三表映射

### yh_spec

每个SPU只建立一条规格定义：

| yh_spec字段 | 来源/规则 |
|---|---|
| `spu_id` | 规范化后的 `yh_goods_spu.id` |
| `spec_code` | `SPEC-PARTS-<spu_id>` |
| `spec_name` | 固定“默认” |
| `unit_id` | `NULL` |
| `param_type` | `枚举` |
| `status` | `1` |
| `sort_order` | `0` |
| `admin_id` | 创建人管理员ID |

### yh_spec_value

同一SPU下，对 `parts.nature` 去重：

| yh_spec_value字段 | 来源/规则 |
|---|---|
| `spec_id` | 当前SPU的默认规格ID |
| `value` | `parts.nature`；为空时写“默认” |
| `extra_price` | `NULL` |
| `admin_id` | 创建人管理员ID |

### yh_sku_spec_value

每个SKU关联一个默认规格值：

| yh_sku_spec_value字段 | 来源/规则 |
|---|---|
| `sku_id` | 新生成的 `yh_goods_sku.id` |
| `value_id` | 当前SKU性质对应的 `yh_spec_value.id` |
| `create_time` | 来源创建时间 |
| `update_time` | 来源更新时间 |
| `delete_time` | `NULL` |

## 七、yh_goods_sku字段对应关系

| yh_goods_sku字段 | parts来源/规则 |
|---|---|
| `id` | 自增 |
| `sku_code` | 唯一来源编码或确定性生成编码 |
| `spu_id` | 规范化后的SPU ID |
| `warranty` | `warranty` |
| `status` | 写`1`，即上架 |
| `data_source` | 固定`parts.sql导入` |
| `hint` | `precautions` |
| `sku_image` | 当前SKU第一张有效普通图片 |
| `admin_id` | `filler → yh_admin_user.id` |
| `is_delete` | `0` |
| `delete_time` | `NULL` |
| `create_time` | `update_time`与`update_time_2`中的较早时间 |
| `update_time` | 两个时间中的较晚时间 |
| `detail` | `product_detail_images`转换的HTML |
| `parameters` | `technical_params` |
| `shipping_address` | `shipping_origin` |
| `delivery_time_desc` | `shipping_time`，展示字段最多100字符，完整原文另行保留 |
| `daily_cutoff_time` | `daily_cutoff_time`，展示字段最多20字符，完整原文另行保留 |
| `retail_price_range` | `retail_ladder_price` |
| `retail_tax` | `retail_tax` |
| `retail_freight` | `retail_shipping` |
| `input_vat_invoice` | `purchase_special_invoice`原文 |
| `input_plain_invoice` | `purchase_general_invoice`原文 |
| `procurement_freight` | `purchase_shipping` |
| `ele_brand` | `applicable_elevator_brand` |
| `_skuKey` | 当前SKU关联的 `yh_spec_value.id`，以字符串形式写入 |
| `special_enabled` | `purchase_special_invoice`包含“含专/含税/含”时为1 |
| `special_price` | 专票启用且采购成本是数值时写采购成本，否则NULL |
| `normal_enabled` | `purchase_general_invoice`包含“含普/含税/含”时为1 |
| `normal_price` | 普票启用且采购成本是数值时写采购成本，否则NULL |
| `ship_type` | 采购运费包含“含/包邮”写`include`，否则`exclude` |
| `ship_remark_include` | 含运费时写 `purchase_shipping` |
| `ship_remark_exclude` | 不含运费时写 `purchase_shipping` |
| `remark` | 合并 `remark` 与 `remark_2`，不超过255字符 |
| `price_enabled` | 无票采购价有效时为1，否则0 |
| `price` | 无票采购成本；字段必填，无有效值时写0且`price_enabled=0` |
| `valid_until` | `quote_validity`能解析为日期时写日期 |
| `valid_until_txt` | `quote_validity`原文 |
| `update_id` | 优先 `filler_2`，其次 `updater`，匹配 `yh_admin_user.id` |

同一SKU由多条parts来源行合并时，SKU主表选择 `update_time_2` 最新的一行作为基准行；其他供应商价格进入供应商报价表。

## 八、零售价格映射

`yh_price_type` 当前为空，需要先建立价格类型：

| name | code | sort | status |
|---|---|---:|---:|
| 零售价格 | `retail_price` | 10 | 1 |

`yh_goods_sku_sales_price`：

| 字段 | 来源/规则 |
|---|---|
| `sku_id` | 当前SKU ID |
| `price_type_id` | “零售价格”类型ID |
| `price` | 可解析为数值的 `parts.retail_price` |
| `admin_id` | 创建人ID |
| `update_user_id` | 更新人ID |
| `create_time` | 来源创建时间 |
| `update_time` | 来源更新时间 |
| `delete_time` | `NULL` |

零售价为空或不是纯数值时，不写销售价格表，不用0冒充真实零售价；原始文本保留到SKU扩展数据或迁移异常清单。

## 九、供应商和采购报价

供应商不参与SKU去重。

```text
parts.supplier
  → yh_supplier
  → yh_goods_quotation.supplier_id
```

同一个SKU出现多个供应商时，每个供应商生成一条报价。

`yh_goods_quotation`映射：

| 报价字段 | 来源/规则 |
|---|---|
| `spu_id` | 当前SKU所属SPU |
| `sku_id` | 当前SKU ID，必须填写 |
| `supplier_id` | 匹配或新增的供应商ID |
| `brand——` | `product_brand` |
| `model` | `model` |
| `price_enabled/price` | 无票采购价标记与数值 |
| `special_enabled/special_price` | 专票标记与采购成本 |
| `normal_enabled/normal_price` | 普票标记与采购成本 |
| `sale_price` | 可解析的 `retail_price`，无值时0 |
| `valid_until` | 可解析日期 |
| `valid_until_txt` | `quote_validity`原文 |
| `status` | 有有效采购价写1，否则0 |
| `entry_time` | 来源更新时间 |
| `admin_id` | 创建人ID |
| `shipping_address` | `shipping_origin` |
| `delivery_time_desc` | `shipping_time` |
| `daily_cutoff_time` | `daily_cutoff_time` |
| `retail_price_range` | `retail_ladder_price` |
| `retail_tax` | `retail_tax` |
| `retail_freight` | `retail_shipping` |
| `input_vat_invoice` | `purchase_special_invoice` |
| `input_plain_invoice` | `purchase_general_invoice` |
| `procurement_freight` | `purchase_shipping` |
| `warranty` | `warranty` |
| `ele_brand` | `applicable_elevator_brand` |
| `ship_type/ship_remark_*` | 根据采购运费内容生成 |
| `remark` | `remark`与`remark_2` |
| `data_source` | `parts.sql导入` |

来源供应商字段中只有一条 `菱威/越沃` 是复合供应商名称，迁移时拆成“菱威”和“越沃”两家，并分别生成报价；其他供应商按完整名称处理。

## 十、无法直接容纳的字段

不新增 `yh_goods_sku_extra`。SKU迁移只写入商城现有SKU、规格、价格和供应商报价表能够直接容纳的数据；无法匹配的SKU级字段不再重复保存。

以下原始信息已经随一条parts对应一条SPU完整保存在 `yh_goods_spu` 和 `yh_goods_spu_extra` 中：

- `substitute_model`
- `category`
- `remark_2`
- 原始采购成本和零售价文本
- 完整的 `shipping_time`
- 完整的 `daily_cutoff_time`

当源文本无法转换为目标字段类型，或超过SKU字段长度时，SKU侧放弃该字段，不截断后冒充完整数据；需要查看原始内容时，以现有SPU及其扩展记录为准。

## 十一、当前SPU迁移的处理选择

当前执行中的脚本是：

```text
一条parts → 一条SPU
```

如果直接在这些SPU下面各建一个SKU，实施简单，但最终仍会保留约595个重复SPU，无法真正形成“一个型号多个SKU”。

### 方案A：兼容当前数据

- 保留当前每条parts对应的SPU。
- 每个SPU创建一个SKU。
- 不做SPU去重。
- 风险低，但商城商品重复较多。

### 方案B：规范化重建（推荐）

- 当前导入完成后，以状态文件识别本次导入的SPU。
- 按“分类+名称+品牌+型号”重新分组。
- 每组保留或重建一个规范SPU。
- 按“SPU+性质+初始零售价”生成SKU。
- 同SKU的不同供应商生成多条报价。
- 不新增SKU扩展表，无法映射的字段不重复迁移。
- 旧重复SPU在确认数据迁移完整后再删除或软删除。

已确认采用方案B。正式写入SKU前，先生成SPU归并、SKU和供应商报价映射清单供复核。

## 十二、建议执行顺序

1. 等当前SPU导入任务结束。
2. 备份本次迁移状态文件及目标表。
3. 生成SPU分组、SKU分组和冲突报告，只预览不写库。
4. 人工检查名称、型号为空和64组多价格冲突。
5. 创建“零售价格”价格类型；不创建SKU扩展表。
6. 生成规范SPU、规格、规格值。
7. 生成SKU和 `yh_sku_spec_value`。
8. 写入SKU销售价格。
9. 写入SKU供应商报价。
10. 对比来源5304条的字段覆盖率。
11. 确认无数据遗漏后，再处理重复SPU。

## 十三、2026-07-28方案B预检结果

使用当前全新 `parts.sql`、完整SPU迁移状态和线上只读结构检查得到：

| 项目 | 数量 |
|---|---:|
| 来源parts | 5304 |
| 规范SPU | 4709 |
| 待生成SKU | 5061 |
| 合并到相同SKU的来源行 | 243 |
| 多来源SKU | 182 |
| 多供应商SKU | 120 |
| 包含多个SKU的规范SPU | 319 |
| 单个SPU最大SKU数 | 5 |
| 待生成供应商报价 | 5155 |
| 没有可用零售价的SKU | 1515 |
| 没有供应商的SKU | 31 |
| 复杂、不能自动转换的零售价来源行 | 51 |
| 来源覆盖 | 5304/5304 |

4709个规范SPU ID在线上全部存在，当前线上SKU、SKU规格关联、SKU销售价格、供应商报价和价格类型表均为空。

相关命令：

```powershell
# 重新生成预检，不写数据库
python jobs\prepare_sku_migration.py

# 检查将要迁移的数量，不写数据库
python jobs\migrate_parts_to_sku.py

# 小批量正式执行
python jobs\migrate_parts_to_sku.py --execute --limit 3

# 全量正式执行
python jobs\migrate_parts_to_sku.py --execute
```

迁移脚本不会删除或软删除任何已有SPU。复杂价格不自动猜测，原文继续保留在 `yh_goods_spu_extra` 中。
