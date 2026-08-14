# 供应商价格对外展示 - 落地方案

> 创建时间: 2026-08-14
> 状态: 部分完成（数据层 + 管理端已完成，销售端待开发）

---

第 1 步：补 display_price_min/max 写入逻辑
这是最基础的，不补它 sales 查不出来。


保存规格价格 → 触发重算 → 写回 parts
删除规格价格 → 触发重算 → 写回 parts
改动点：variants.py 的 POST / PUT / DELETE 三个接口末尾加一行调用。

第 2 步：数据迁移

拉正式库 → 匹配 OA 供应商 → 导入测试库 → 验证
第 3 步：sales 列表页重写

有规格（多）→ 查对外价格区间
有规格（单）→ 查该规格价格
无规格 → parts.purchase_cost
第 4 步：sales 详情页重写

每个规格组合 → 展示价格（不含供应商）

## 一、需求概述

1. 通过 `oa_supplier_id` 关联 OA 供应商表，获取供应商名称、税率、开票能力
2. 根据供应商开票能力，前端控制价格输入框和对外展示开关的禁用/启用
3. 填写一个价格 → 根据 OA 税点自动计算另外两个价格
4. 员工自主选择对外展示的价格（同一规格组合下最多选 3 个，用 SET 字段）
5. 有规格的组合展示对外价格区间，无规格的组合展示 parts 表价格
6. 详情页（sales 端）不展示供应商，只展示价格

---


## 四、待开发：销售端（sales.py）

### 4.2 列表页（`_fetch_parts_products` 重写）

```python
def _extract_display_prices(variant_prices):
    """从 variant_prices 中提取所有对外展示的价格"""
    prices = []
    for vp in variant_prices:
        fields = (vp.get('external_price_fields') or '').split(',')
        if 'no_tax' in fields and vp.get('purchase_cost'):
            prices.append(float(vp['purchase_cost']))
        if 'special' in fields and vp.get('purchase_special_invoice'):
            prices.append(float(vp['purchase_special_invoice']))
        if 'general' in fields and vp.get('purchase_general_invoice'):
            prices.append(float(vp['purchase_general_invoice']))
    return prices
```

**展示格式**：
- 多规格：`display_price_min ~ display_price_max`（如 "¥100 ~ ¥113"）
- 单规格：直接展示该规格的价格（如 "¥100" 或 "¥100 / ¥113 / ¥109"）
- 无规格：`parts.purchase_cost`

### 4.3 详情页（`_fetch_parts_variant_quotes` 重写）


**改后**：
- 不展示供应商名称
- 不展示供应商选择逻辑
- 每个规格组合直接展示对应的价格（最多 3 个）

```python
# 查所有 variant prices
# 按 variant_group_id 分组
# 每组展示 external_price_fields 对应的价格
```


## 五、接口清单

### 5.2 修改接口

| 接口 | 变更 |
|---|---|
| `/api/products/{id}/variant-prices/{pid}` PUT | 请求体新增 `oa_supplier_id` + `external_price_fields`；保存后触发 display_price_min/max 重算 |
| `/api/products/{id}/variant-prices/{pid}` DELETE | 删除后触发 display_price_min/max 重算 |
| `/api/sales/products` GET | 重写查询逻辑（有规格查对外价格区间，无规格查 parts） |
| `/api/sales/parts/{part_id}/variant-quotes` GET | 重写：不展示供应商，只展示价格 |

---

## 六、文件改动清单

### 已完成

| 文件 | 改动 |
|---|---|
| `parts_system/shared.py` | +OA_DB_CONFIG, +get_oa_db(), +migration 4 列 |
| `parts_system/routes/variants.py` | +请求模型字段, +保存/更新SQL, +OA查询接口 |
| `parts_system/routes/catalog.py` | /api/suppliers 改走 OA |
| `static/js/variants.js` | OA选供应商, 开票能力校验, 价格自动计算, Toggle开关 |
| `static/css/product-detail.css` | Toggle样式, 禁用输入框样式 |

### 待完成

| 文件 | 改动 |
|---|---|
| `parts_system/routes/variants.py` | 保存/删除后调用 `_recalculate_part_display_price` |
| `parts_system/routes/sales.py` | 重写 `_fetch_parts_products`（列表页） |
| `parts_system/routes/sales.py` | 重写 `_fetch_parts_variant_quotes`（详情页，去掉供应商逻辑） |

---

## 七、数据迁移策略

### 测试环境（当前）

- 双写兼容：历史数据不动（`supplier` 字段保留），新增走 OA
- `/api/suppliers` 返回 OA 供应商 + 本地历史名称兜底
- 前端：有 `oa_supplier_id` 的走 OA 校验逻辑；没有的走兼容模式

### 正式环境（上线时）

- 一次性迁移：导出生产数据 → 匹配 OA 供应商 → 按新结构导入
- 导入后所有记录都有 `oa_supplier_id`，无历史包袱
- 删除本地查询兜底逻辑

---

## 八、ponytail 审阅记录


### SET vs 三个 boolean

- **改前方案**：no_tax_external_visible / special_external_visible / general_external_visible（3 列）
- **改后方案**：external_price_fields SET('no_tax','special','generic')（1 列）
- **净减**：少 2 个数据库列、少 2 个请求字段

### 前端交互简化

- **改前**：复选框启用 → 填写价格 → 独立卡片选对外展示
- **改后**：直接填写（OA 不支持则禁用）→ Toggle 开关放在价格旁
- **净减**：删除 1 个函数、1 个独立卡片、3 个复选框、1 个 badge

### 销售端查询

- **改前**：NOT EXISTS 选 1 个供应商 → 1 个价格
- **改后**：取所有供应商的对外价格 → min/max 区间
- **核心变化**：不再选"最佳供应商"，直接查对外展示的价格
