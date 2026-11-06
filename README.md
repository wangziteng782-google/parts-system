# parts-system 配件批改系统

## 系统架构

- Nginx 和 MySQL。
- FastAPI 使用独立 Python 3.11 虚拟环境。
- Uvicorn 只监听 `127.0.0.1:8055`，不直接开放公网端口。
- systemd 负责开机启动、异常重启和运行状态。
- Nginx 将测试域名反向代理到 Uvicorn。

## 页面分工与价格口径

| 页面 | 使用方 | 做什么 |
| --- | --- | --- |
| `/inquiry-match` | 采购 | 把询价记录关联到产品库 SKU，核对采购价 |
| `/sales` | 销售 | 查商品、看销售参考价、提交问题反馈 |

采购侧录采购价，销售价由系统算，销售不需要也不会看到成本价。

价格链条：采购在询价单里录入采购价（`jh_goods_price` 无税、`jh_goods_price_has_tax` 含税），OA 按每条报价的利润系数 `profit_rate` 算出报价金额，同步落到本地 `inquiry_quotes.purchase_price`。销售端展示的就是这个已经算好的金额，不要再乘一次系数。

`/sales` 的取价规则（`parts_system/routes/sales.py`）：

- 来自询价记录的商品，销售参考价取 `inquiry_quotes` 里 `is_selected=1` 那条的 `purchase_price`，即 OA 已经算过利润的报价金额。查不到选中报价时才退回按销售系数换算。
- 来自配件库的商品，用 `_display_price()` / `_scaled_positive_price()` 把采购侧字段乘上销售系数：产品名称优先（`SALES_PRODUCT_NAME_MULTIPLIERS`，目前制动器、梯级链 1.10），产品分类次之（`SALES_PRODUCT_TYPE_MULTIPLIERS`，暂空），都没命中用默认 1.15。
- 新增销售端价格展示时，走上面两条路径，不要直接读 `purchase_*` 原始字段，也不要返回 `purchase_cost`。

采购报价（`purchase_price`，即单件商品的采购成本）不返回给销售端，`/api/sales/products` 的响应里没有这个字段，详情弹窗也不展示。新增字段时守住这条：成本价不出接口。

销售端仍会展示的采购侧数据（页面上带"采购"字样）：询价列表"询价报价信息"列的无税运费报价、含税运费报价，询价详情弹窗顶部的两个运费报价，配件详情里的采购运费。这些是采购原始信息，用于销售判断，不属于售价。

已知遗留：询价列表按价格排序时用的是 `price_sql` 算出的成本价，与展示价不是同一口径。同一列表里系数一致时顺序不受影响，混合不同利润系数的记录时可能差一位。
