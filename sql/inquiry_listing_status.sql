-- 正式环境一次性执行脚本
-- 适用数据库：parts_database
-- 用途：销售询价记录反馈与上下架状态控制。

USE `parts_database`;
-----------------1---------------
ALTER TABLE `sales_product_feedback`
    ADD COLUMN `inquiry_mission_id` BIGINT DEFAULT NULL
    COMMENT '关联OA询价任务ID，对应yh_query_goods_mission.id'
    AFTER `inquiry_goods_id`,
    ADD KEY `idx_feedback_inquiry_mission` (`inquiry_mission_id`, `status`);

-----------------2---------------
CREATE TABLE `sales_inquiry_listing_status` (
    `inquiry_mission_id` BIGINT NOT NULL
        COMMENT 'OA询价任务ID，对应yh_query_goods_mission.id',
    `inquiry_goods_id` BIGINT DEFAULT NULL
        COMMENT 'OA询价商品ID，对应yh_query_order_goods.id',
    `listing_status` TINYINT(1) NOT NULL DEFAULT 1
        COMMENT '销售端展示状态：1上架，0下架',
    `feedback_id` BIGINT DEFAULT NULL
        COMMENT '触发本次处理的销售反馈ID，对应sales_product_feedback.id',
    `reason` VARCHAR(500) DEFAULT NULL
        COMMENT '下架或恢复原因',
    `updated_by` INT UNSIGNED DEFAULT NULL
        COMMENT '最后操作人ID，对应yh_admin_user.id',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        COMMENT '创建时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
        COMMENT '更新时间',
    PRIMARY KEY (`inquiry_mission_id`),
    KEY `idx_listing_status` (`listing_status`, `updated_at`),
    KEY `idx_listing_goods` (`inquiry_goods_id`),
    KEY `idx_listing_feedback` (`feedback_id`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='销售端询价记录上下架状态表';
