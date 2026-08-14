-- 正式环境一次性执行脚本
-- 适用数据库：parts_database
-- 用途：记录销售页面搜索行为，只保留查询人、查询内容、查询时间。

USE `parts_database`;

CREATE TABLE `sales_query_logs` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '日志ID',
    `user_id` INT UNSIGNED DEFAULT NULL COMMENT '查询人ID，对应yh_admin_user.id',
    `user_name` VARCHAR(100) DEFAULT NULL COMMENT '查询人姓名',
    `query_keyword` VARCHAR(255) DEFAULT NULL COMMENT '查询内容/搜索关键词',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '查询时间',
    PRIMARY KEY (`id`),
    KEY `idx_sales_query_user_time` (`user_id`, `created_at`),
    KEY `idx_sales_query_user_name_time` (`user_name`, `created_at`),
    KEY `idx_sales_query_keyword_time` (`query_keyword`, `created_at`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='销售查询日志表';
