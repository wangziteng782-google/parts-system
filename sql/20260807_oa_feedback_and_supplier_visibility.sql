-- 正式环境一次性建表脚本
-- 适用数据库：parts_database
-- 前提：
-- 1. product_variant_prices 表已存在，且尚无 is_external_visible 字段；
-- 2. sales_product_feedback 表尚不存在。
-- 请在正式环境完整执行本文件一次，不要重复执行。

USE `parts_database`;

-- 一、现有供应商报价表增加“是否对外展示”字段。
-- 已有报价默认不对外展示。
ALTER TABLE `product_variant_prices`
    ADD COLUMN `is_external_visible` TINYINT(1) NOT NULL DEFAULT 0
    COMMENT '是否对外展示：0否，1是'
    AFTER `is_default`;

-- 二、新建销售商品反馈表。
CREATE TABLE `sales_product_feedback` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '反馈ID',
    `parts_id` INT DEFAULT NULL COMMENT '关联配件ID，对应parts.id',
    `inquiry_goods_id` BIGINT DEFAULT NULL COMMENT '关联OA询价商品ID',
    `feedback_user_id` INT UNSIGNED DEFAULT NULL COMMENT '反馈人ID，对应yh_admin_user.id',
    `source_type` VARCHAR(20) NOT NULL COMMENT '反馈来源：parts配件库、inquiry询价记录',
    `issue_types` VARCHAR(100) NOT NULL COMMENT '问题类型，多个类型使用英文逗号分隔',
    `description` TEXT NOT NULL COMMENT '反馈内容',
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending'
        COMMENT '处理状态：pending待处理、completed已完成、ignored已忽略',
    `handled_by` INT UNSIGNED DEFAULT NULL COMMENT '处理人ID，对应yh_admin_user.id',
    `handled_at` DATETIME DEFAULT NULL COMMENT '处理时间',
    `handle_remark` VARCHAR(500) DEFAULT NULL COMMENT '处理说明',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '反馈时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY `idx_feedback_parts_status` (`parts_id`, `status`, `created_at`),
    KEY `idx_feedback_inquiry_goods` (`inquiry_goods_id`),
    KEY `idx_feedback_user_time` (`feedback_user_id`, `created_at`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='销售商品问题反馈记录表';
