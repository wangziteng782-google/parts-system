-- 正式环境一次性执行脚本
-- 适用数据库：parts_database
-- 用途：1) 规格组合价格表增加 supplier_id 和对外展示字段; 2) 配件表缓存对外价格区间
USE `parts_database`;

-- product_variant_prices 加 2 列
ALTER TABLE product_variant_prices
  ADD COLUMN oa_supplier_id BIGINT(20) NULL COMMENT 'OA供应商ID',
  ADD COLUMN external_price_fields SET('no_tax','special','general') NULL COMMENT '对外展示价格字段';

-- parts 加 2 列
ALTER TABLE parts
  ADD COLUMN display_price_min DECIMAL(14,2) NULL COMMENT '组合中最低价',
  ADD COLUMN display_price_max DECIMAL(14,2) NULL COMMENT '组合中最高价';

