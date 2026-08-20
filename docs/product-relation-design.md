# 关联产品设计文档

## 需求概述

在 goods 页面新增"关联产品"功能，允许产品之间建立关联关系，在销售查询时展示关联产品并标注"替代品"标签。

## 关联逻辑

- A 可以关联 B，B 也可以关联 A，各自独立操作
- 关联后效果：搜 A 能出 B，搜 B 也能出 A
- 关联产品展示完整产品信息（型号、价格等）
- 在非主型号但为替代品的产品上显示"替代品"标签

## 数据库设计

### 新建表 `product_relations`

```sql
CREATE TABLE product_relations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    related_product_id INT NOT NULL,
    UNIQUE KEY uk_relation (product_id, related_product_id),
    INDEX idx_product (product_id)
);
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INT AUTO_INCREMENT | 主键 |
| `product_id` | INT NOT NULL | 产品ID |
| `related_product_id` | INT NOT NULL | 关联产品ID |

### 存储方案：双向存储

- A→B 存一条，B→A 也存一条
- 查询时只需 `WHERE product_id=A`，简单高效
- 插入/删除用事务保证两条记录一致
- 应用层校验阻止自关联（product_id = related_product_id）

**选择理由**：
- 查询简单，`product_id` 加索引即可，性能最优
- 应用层逻辑清晰，不需要 OR 条件
- 存储成本可忽略（关联关系数据量小）
- 典型的"空间换时间"，在数据量小、查询频繁的场景下维护成本更低

## 实现路线

### 后端 API

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/products/{id}/relations` | GET | 获取产品的关联产品列表 |
| `/api/products/{id}/relations` | POST | 添加关联（body: `{related_product_id}`） |
| `/api/products/{id}/relations/{rid}` | DELETE | 删除关联 |

### 前端

- 替代型号旁边加"关联产品"按钮
- 点击弹出搜索弹窗（复用现有产品搜索）
- 选择产品后保存关联
- 产品详情页展示关联产品列表，可删除

### 实现步骤

1. 后端：`products.py` 新增 3 个接口
2. 前端：`products.js` 加按钮 + 弹窗逻辑
3. 数据库：表已建好

## 待确认项

- [ ] 一键复制功能的细节（是否复制规格、供应商价格、图片等）
