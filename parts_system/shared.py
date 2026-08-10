from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Dict, Optional, List
import pymysql
from dotenv import load_dotenv
import logging
import os
import json
import mimetypes
import time
import uuid
from itertools import product
from datetime import datetime
from urllib.parse import quote
from qiniu import Auth, put_data

# ========== 日志配置 ==========
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = PROJECT_ROOT
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

logger = logging.getLogger("parts_system")
logger.setLevel(logging.DEBUG)
logger.handlers.clear()
logger.propagate = False

# 只输出到控制台，不创建文件日志。
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))

logger.addHandler(console_handler)

logger.info("=" * 60)
logger.info("电梯配件管理系统启动 | 日志输出方式=仅控制台 | 级别=DEBUG")
logger.info("=" * 60)

DB_CONFIG = {
    'host': os.getenv('PARTS_DB_HOST', 'localhost').strip(),
    'port': int(os.getenv('PARTS_DB_PORT', '3306')),
    'user': os.getenv('PARTS_DB_USER', 'root').strip(),
    'password': os.getenv('PARTS_DB_PASSWORD', '1234'),
    'database': os.getenv('PARTS_DB_NAME', 'parts_database').strip(),
    'charset': os.getenv('PARTS_DB_CHARSET', 'utf8mb4').strip(),
    'cursorclass': pymysql.cursors.DictCursor,
    'connect_timeout': int(os.getenv('PARTS_DB_CONNECT_TIMEOUT', '10')),
}

QINIU_LOCAL_CONFIG_FILE = os.path.join(LOG_DIR, 'qiniu_config.local.json')


def load_qiniu_local_config():
    """读取不进入版本管理的本地七牛配置；环境变量优先级更高。"""
    if not os.path.exists(QINIU_LOCAL_CONFIG_FILE):
        return {}
    try:
        with open(QINIU_LOCAL_CONFIG_FILE, 'r', encoding='utf-8') as config_file:
            config = json.load(config_file)
        return config if isinstance(config, dict) else {}
    except Exception as e:
        logger.warning(f"[七牛配置] 本地配置文件读取失败 | error={e}")
        return {}


_qiniu_local_config = load_qiniu_local_config()
QINIU_CONFIG = {
    'access_key': os.getenv('QINIU_ACCESS_KEY', '').strip() or str(_qiniu_local_config.get('access_key', '')).strip(),
    'secret_key': os.getenv('QINIU_SECRET_KEY', '').strip() or str(_qiniu_local_config.get('secret_key', '')).strip(),
    'bucket': os.getenv('QINIU_BUCKET', '').strip() or str(_qiniu_local_config.get('bucket', '')).strip(),
    'domain': (
        os.getenv('QINIU_DOMAIN', '').strip()
        or str(_qiniu_local_config.get('domain', '')).strip()
    ).rstrip('/'),
}
MAX_UPLOAD_IMAGE_SIZE = 10 * 1024 * 1024
MAX_UPLOAD_IMAGE_COUNT = 20
ALLOWED_IMAGE_MIME_TYPES = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/bmp': '.bmp',
}


# 产品分类方案（来源：配件分类方案.xlsx / sheet2）。
# 黄色单元格为一级分类，B 列普通单元格为二级分类，C 列为最终三级分类。
PRODUCT_CLASSIFICATION_TREE = [
    {
        "name": "机房部件",
        "children": [
            {"name": "控制柜类", "children": ["主板", "驱动板", "变频器", "机房话机", "制动电阻", "开关电源", "一体机", "变频器风扇", "接触器", "相序继电器", "松闸电源"]},
            {"name": "曳引机类", "children": ["曳引机", "编码器", "制动器", "曳引轮"]},
            {"name": "限速器类", "children": ["限速器", "限速器开关"]},
        ],
    },
    {
        "name": "轿厢部件",
        "children": [
            {"name": "操纵盘类", "children": ["轿厢显示板", "指令板", "轿厢通讯板", "按钮"]},
            {"name": "轿顶检修箱类", "children": ["轿顶板", "应急电池", "检修按钮"]},
            {"name": "平层感应器类", "children": ["平层感应器", "平层开关"]},
            {"name": "反绳轮类", "children": ["反绳轮"]},
            {"name": "光幕类", "children": ["光幕"]},
        ],
    },
    {
        "name": "井道部件",
        "children": [
            {"name": "井道灯类", "children": ["井道灯"]},
            {"name": "钢丝绳类", "children": ["钢丝绳", "钢丝绳绳头"]},
            {"name": "导轨类", "children": ["导轨", "导轨支架", "连接板", "螺丝"]},
            {"name": "钢带类", "children": ["钢带"]},
            {"name": "电缆线类", "children": ["随行电缆", "门锁电缆", "安全回路电缆"]},
            {"name": "外呼部件", "children": ["外呼显示板", "外呼板"]},
        ],
    },
    {
        "name": "底坑部件",
        "children": [
            {"name": "底坑检修盒类", "children": ["检修开关"]},
            {"name": "缓冲器类", "children": ["缓冲器", "缓冲器开关"]},
            {"name": "涨紧装置类", "children": ["张紧轮", "整套张紧装置"]},
            {"name": "安全钳类", "children": ["安全钳"]},
            {"name": "导靴类", "children": ["导靴轮", "导靴"]},
        ],
    },
    {
        "name": "厅轿门部件",
        "children": [
            {"name": "门电机类", "children": ["门电机", "电机轮"]},
            {"name": "门机变频器类", "children": ["门机变频器"]},
            {"name": "地坎类", "children": ["地坎"]},
            {"name": "门板类", "children": ["厅门板", "轿门板"]},
            {"name": "门头类", "children": ["厅门门头", "轿门门头", "门头钢丝绳", "门挂板", "锁钩", "门锁装置"]},
            {"name": "门轮类", "children": ["门挂轮"]},
            {"name": "门刀类", "children": ["门刀"]},
            {"name": "门机皮带类", "children": ["门机皮带"]},
        ],
    },
    {"name": "其他机械类", "children": [
        {"name": "其他机械类", "children": ["砝码"]},
    ]},
    {"name": "其他电子类", "children": []},
    {"name": "扶梯配件", "children": []},
    {"name": "对讲类", "children": [
        {"name": "对讲类", "children": ["无线对讲", "有线对讲"]},
    ]},
]

PRODUCT_TYPE_VALUES = [
    third_level
    for first_level in PRODUCT_CLASSIFICATION_TREE
    for second_level in first_level["children"]
    for third_level in second_level["children"]
]

CLASSIFICATION_FILE = os.path.join(LOG_DIR, "product_classifications.json")


def refresh_product_type_values():
    """分类树变更后刷新允许写入的三级分类集合。"""
    # 保持列表对象不变，让按业务拆分后的各路由模块始终看到最新数据。
    PRODUCT_TYPE_VALUES[:] = [
        third_level
        for first_level in PRODUCT_CLASSIFICATION_TREE
        for second_level in first_level["children"]
        for third_level in second_level["children"]
    ]


def load_classification_tree():
    """优先加载运行期间新增的分类；首次运行使用 Excel 内置方案。"""
    global PRODUCT_CLASSIFICATION_TREE
    if not os.path.exists(CLASSIFICATION_FILE):
        return
    try:
        with open(CLASSIFICATION_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, list):
            PRODUCT_CLASSIFICATION_TREE = stored
            refresh_product_type_values()
    except Exception as e:
        logger.warning(f"[分类树] 读取持久化分类失败，使用默认方案 | error={e}")


def save_classification_tree():
    with open(CLASSIFICATION_FILE, "w", encoding="utf-8") as f:
        json.dump(PRODUCT_CLASSIFICATION_TREE, f, ensure_ascii=False, indent=2)


load_classification_tree()


def get_db():
    conn = pymysql.connect(**DB_CONFIG)
    ensure_technical_params_column(conn)
    # 规格组合表采用惰性初始化，确保现有数据库升级时无需手工执行脚本。
    ensure_product_variant_tables(conn)
    ensure_product_spec_required_rules(conn)
    return conn


def ensure_employee_operation_logs_table(conn):
    """Create the employee operation log table used by the audit page."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_operation_logs (
            id BIGINT NOT NULL AUTO_INCREMENT COMMENT '日志ID',
            user_id INT UNSIGNED NOT NULL COMMENT '操作人ID，对应yh_admin_user.id',
            part_id INT DEFAULT NULL COMMENT '配件ID；删除后仍保留原ID',
            product_name_snapshot VARCHAR(255) DEFAULT NULL COMMENT '操作时的产品名称快照',
            model_snapshot VARCHAR(255) DEFAULT NULL COMMENT '操作时的产品型号快照',
            operation_type VARCHAR(20) NOT NULL COMMENT '操作类型：CREATE新增、UPDATE修改、DELETE删除',
            module_code VARCHAR(30) NOT NULL DEFAULT 'PRODUCT' COMMENT '变更模块',
            detail TEXT NOT NULL COMMENT '操作内容或变更摘要',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
            PRIMARY KEY (id),
            KEY idx_operation_logs_user_time (user_id, created_at),
            KEY idx_operation_logs_part_time (part_id, created_at),
            KEY idx_operation_logs_type_time (operation_type, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='员工新增、修改、删除配件的操作日志'
        """
    )

    # 兼容已经存在的日志表：产品被修改或删除后，仍可按名称和型号聚合历史。
    cursor.execute("SHOW COLUMNS FROM employee_operation_logs")
    existing_columns = {row["Field"] for row in cursor.fetchall()}
    if "product_name_snapshot" not in existing_columns:
        cursor.execute(
            """ALTER TABLE employee_operation_logs
               ADD COLUMN product_name_snapshot VARCHAR(255) DEFAULT NULL
               COMMENT '操作时的产品名称快照' AFTER part_id"""
        )
    if "model_snapshot" not in existing_columns:
        cursor.execute(
            """ALTER TABLE employee_operation_logs
               ADD COLUMN model_snapshot VARCHAR(255) DEFAULT NULL
               COMMENT '操作时的产品型号快照' AFTER product_name_snapshot"""
        )

    # 为升级前的现有日志补齐当前产品快照；已被删除且无法还原的记录保留原part_id。
    cursor.execute(
        """UPDATE employee_operation_logs l
           JOIN parts p ON p.id=l.part_id
           SET l.product_name_snapshot=COALESCE(l.product_name_snapshot,p.product_name),
               l.model_snapshot=COALESCE(l.model_snapshot,p.model)
           WHERE l.product_name_snapshot IS NULL OR l.model_snapshot IS NULL"""
    )

    # 旧删除日志无法再关联 parts，从既有摘要“产品名称：…；型号：…”中恢复快照。
    cursor.execute(
        """SELECT id, part_id, detail
           FROM employee_operation_logs
           WHERE operation_type='DELETE'
             AND (product_name_snapshot IS NULL OR model_snapshot IS NULL)"""
    )
    recovered_snapshots = []
    for row in cursor.fetchall():
        detail = str(row.get("detail") or "")
        name_marker = "产品名称："
        model_marker = "；型号："
        if name_marker not in detail or model_marker not in detail:
            continue
        snapshot_text = detail.split(name_marker, 1)[1]
        product_name, model = snapshot_text.split(model_marker, 1)
        recovered_snapshots.append(
            (product_name.strip() or None, model.strip() or None, row["id"])
        )
    if recovered_snapshots:
        cursor.executemany(
            """UPDATE employee_operation_logs
               SET product_name_snapshot=COALESCE(product_name_snapshot,%s),
                   model_snapshot=COALESCE(model_snapshot,%s)
               WHERE id=%s""",
            recovered_snapshots,
        )

    # 将同一part_id已经恢复出的名称、型号传播给该产品的其他旧日志。
    cursor.execute(
        """SELECT DISTINCT part_id
           FROM employee_operation_logs
           WHERE part_id IS NOT NULL
             AND (product_name_snapshot IS NULL OR model_snapshot IS NULL)"""
    )
    missing_part_ids = [row["part_id"] for row in cursor.fetchall()]
    if missing_part_ids:
        placeholders = ",".join(["%s"] * len(missing_part_ids))
        cursor.execute(
            f"""SELECT part_id, product_name_snapshot, model_snapshot
                FROM employee_operation_logs
                WHERE part_id IN ({placeholders})
                  AND product_name_snapshot IS NOT NULL
                  AND model_snapshot IS NOT NULL
                ORDER BY id DESC""",
            missing_part_ids,
        )
        part_snapshots = {}
        for row in cursor.fetchall():
            part_snapshots.setdefault(
                row["part_id"],
                (row["product_name_snapshot"], row["model_snapshot"]),
            )
        if part_snapshots:
            cursor.executemany(
                """UPDATE employee_operation_logs
                   SET product_name_snapshot=COALESCE(product_name_snapshot,%s),
                       model_snapshot=COALESCE(model_snapshot,%s)
                   WHERE part_id=%s
                     AND (product_name_snapshot IS NULL OR model_snapshot IS NULL)""",
                [
                    (product_name, model, part_id)
                    for part_id, (product_name, model) in part_snapshots.items()
                ],
            )
    conn.commit()


def ensure_technical_params_column(conn):
    """技术参数仍保存为单字段，但使用 TEXT 支持多行、较长内容。"""
    cursor = conn.cursor()
    cursor.execute("SHOW COLUMNS FROM parts LIKE 'technical_params'")
    column = cursor.fetchone()
    if column and str(column.get('Type', '')).lower() != 'text':
        logger.info("[数据库迁移] parts.technical_params -> TEXT")
        cursor.execute("ALTER TABLE parts MODIFY COLUMN technical_params TEXT NULL COMMENT '技术参数（多行文本）'")


def ensure_duplicate_marks_table(conn):
    """确保员工重复标记表存在；只创建表，不修改现有产品数据。"""
    cursor = conn.cursor()
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS duplicate_product_marks (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            product_id INT NOT NULL,
            product_name VARCHAR(255) NULL,
            model VARCHAR(500) NULL,
            marked_by VARCHAR(100) NOT NULL DEFAULT '当前员工',
            marked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_duplicate_product_mark (product_id),
            KEY idx_duplicate_marked_at (marked_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )


def ensure_product_spec_required_rules(conn):
    """确保产品默认规格规则表结构可用；业务规则统一由数据库维护。"""
    cursor = conn.cursor()
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS product_spec_required_rules (
            id BIGINT NOT NULL AUTO_INCREMENT COMMENT '规则ID',
            product_type VARCHAR(100) NOT NULL DEFAULT ''
                COMMENT '匹配的产品分类，空字符串表示不限制产品分类',
            product_name VARCHAR(255) NOT NULL DEFAULT ''
                COMMENT '匹配的产品名称，空字符串表示不限制产品名称',
            product_name_match_mode VARCHAR(20) NOT NULL DEFAULT 'exact'
                COMMENT '产品名称匹配方式：exact精确匹配，contains包含匹配',
            spec_name VARCHAR(100) NOT NULL COMMENT '必须存在的规格名称',
            is_required TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否必备规格：1是，0否',
            is_locked TINYINT(1) NOT NULL DEFAULT 1 COMMENT '规格名是否锁定：1不可改名，0可修改',
            sort_order INT NOT NULL DEFAULT 0 COMMENT '规格显示顺序',
            status TINYINT(1) NOT NULL DEFAULT 1 COMMENT '状态：1启用，0停用',
            remark VARCHAR(500) NULL COMMENT '规则说明',
            created_by BIGINT NULL COMMENT '创建员工ID',
            updated_by BIGINT NULL COMMENT '最后修改员工ID',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP COMMENT '最后修改时间',
            PRIMARY KEY (id),
            UNIQUE KEY uq_product_required_spec
                (product_type, product_name, product_name_match_mode, spec_name),
            KEY idx_required_spec_match (product_type, product_name, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='产品必备规格匹配规则表'"""
    )
    cursor.execute(
        """SELECT TABLE_COLLATION AS table_collation
           FROM information_schema.TABLES
           WHERE TABLE_SCHEMA=DATABASE()
             AND TABLE_NAME='product_spec_required_rules'"""
    )
    rule_table = cursor.fetchone()
    if rule_table and rule_table.get('table_collation') != 'utf8mb4_unicode_ci':
        logger.info(
            "[数据库迁移] product_spec_required_rules -> utf8mb4_unicode_ci"
        )
        cursor.execute(
            """ALTER TABLE product_spec_required_rules
               CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"""
        )
    cursor.execute(
        """SELECT COLUMN_DEFAULT AS column_default, COLUMN_COMMENT AS column_comment
           FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE()
             AND TABLE_NAME='product_spec_required_rules'
             AND COLUMN_NAME='product_name'"""
    )
    product_name_column = cursor.fetchone()
    expected_comment = "匹配的产品名称，空字符串表示不限制产品名称"
    if (
        product_name_column
        and (
            product_name_column.get('column_default') != ''
            or product_name_column.get('column_comment') != expected_comment
        )
    ):
        logger.info(
            "[数据库迁移] product_spec_required_rules.product_name 支持分类级规则"
        )
        cursor.execute(
            """ALTER TABLE product_spec_required_rules
               MODIFY COLUMN product_name VARCHAR(255) NOT NULL DEFAULT ''
               COMMENT '匹配的产品名称，空字符串表示不限制产品名称'"""
        )
    cursor.execute(
        """SELECT COLUMN_NAME
           FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE()
             AND TABLE_NAME='product_spec_required_rules'
             AND COLUMN_NAME='product_name_match_mode'"""
    )
    if not cursor.fetchone():
        logger.info(
            "[数据库迁移] product_spec_required_rules 新增产品名称匹配方式"
        )
        cursor.execute(
            """ALTER TABLE product_spec_required_rules
               ADD COLUMN product_name_match_mode VARCHAR(20) NOT NULL
               DEFAULT 'exact'
               COMMENT '产品名称匹配方式：exact精确匹配，contains包含匹配'
               AFTER product_name"""
        )
    cursor.execute(
        """SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS index_columns
           FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA=DATABASE()
             AND TABLE_NAME='product_spec_required_rules'
             AND INDEX_NAME='uq_product_required_spec'
           GROUP BY INDEX_NAME"""
    )
    unique_index = cursor.fetchone()
    expected_index_columns = (
        "product_type,product_name,product_name_match_mode,spec_name"
    )
    if (
        unique_index
        and unique_index.get("index_columns") != expected_index_columns
    ):
        logger.info(
            "[数据库迁移] product_spec_required_rules 更新规则唯一索引"
        )
        cursor.execute(
            """ALTER TABLE product_spec_required_rules
               DROP INDEX uq_product_required_spec,
               ADD UNIQUE KEY uq_product_required_spec
               (product_type, product_name, product_name_match_mode, spec_name)"""
        )
    cursor.execute(
        """SELECT COLUMN_DEFAULT AS column_default, COLUMN_COMMENT AS column_comment
           FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE()
             AND TABLE_NAME='product_spec_required_rules'
             AND COLUMN_NAME='product_type'"""
    )
    product_type_column = cursor.fetchone()
    expected_type_comment = "匹配的产品分类，空字符串表示不限制产品分类"
    if (
        product_type_column
        and (
            product_type_column.get('column_default') != ''
            or product_type_column.get('column_comment') != expected_type_comment
        )
    ):
        logger.info(
            "[数据库迁移] product_spec_required_rules.product_type 支持名称级规则"
        )
        cursor.execute(
            """ALTER TABLE product_spec_required_rules
               MODIFY COLUMN product_type VARCHAR(100) NOT NULL DEFAULT ''
               COMMENT '匹配的产品分类，空字符串表示不限制产品分类'"""
        )
    conn.commit()


def ensure_product_variant_tables(conn):
    """创建产品规格值和规格组合价格表；技术参数改由 parts.technical_params 主表字段提供。"""
    cursor = conn.cursor()
    cursor.execute("SHOW COLUMNS FROM parts LIKE 'variant_groups_initialized'")
    if not cursor.fetchone():
        logger.info("[数据库迁移] parts 新增 variant_groups_initialized 字段")
        cursor.execute(
            """ALTER TABLE parts
               ADD COLUMN variant_groups_initialized TINYINT(1) NOT NULL DEFAULT 0
               COMMENT '规格组合是否已完成首次持久化：0否，1是'"""
        )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS product_variant_specs (
            id BIGINT NOT NULL AUTO_INCREMENT COMMENT '规格明细ID',
            part_id INT NOT NULL COMMENT '产品主表ID，对应parts.id',
            spec_name VARCHAR(100) NOT NULL COMMENT '规格名',
            spec_value VARCHAR(255) NOT NULL COMMENT '规格值',
            sort_order INT NOT NULL DEFAULT 0 COMMENT '规格显示顺序',
            is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否有效：1有效，0已删除但保留历史组合',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后修改时间',
            PRIMARY KEY (id),
            UNIQUE KEY uq_variant_spec_value (part_id, spec_name, spec_value),
            KEY idx_variant_specs_name (part_id, spec_name),
            CONSTRAINT fk_variant_specs_part FOREIGN KEY (part_id) REFERENCES parts(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='产品规格字典表：每个规格名和规格值只保存一次'"""
    )
    cursor.execute("SHOW COLUMNS FROM product_variant_specs LIKE 'is_active'")
    if not cursor.fetchone():
        logger.info("[数据库迁移] product_variant_specs 新增 is_active 字段")
        cursor.execute(
            """ALTER TABLE product_variant_specs
               ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1
               COMMENT '是否有效：1有效，0已删除但保留历史组合'
               AFTER sort_order"""
        )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS product_variant_prices (
            id BIGINT NOT NULL AUTO_INCREMENT COMMENT '规格组合价格ID',
            part_id INT NOT NULL COMMENT '产品主表ID，对应parts.id',
            variant_group_id VARCHAR(64) NOT NULL COMMENT '完整规格组合ID',
            supplier VARCHAR(255) NOT NULL COMMENT '供应商名称',
            purchase_cost DECIMAL(14,2) NULL COMMENT '采购成本价/买价',
            no_tax_price DECIMAL(14,2) NULL COMMENT '不含票单价',
            purchase_special_invoice DECIMAL(14,2) NULL COMMENT '采购专票价/含专票价',
            purchase_general_invoice DECIMAL(14,2) NULL COMMENT '采购普票价/含普票价',
            purchase_shipping DECIMAL(14,2) NULL COMMENT '采购运费/含运费',
            freight_remark VARCHAR(255) NULL COMMENT '运费备注',
            retail_price DECIMAL(14,2) NULL COMMENT '零售价格',
            retail_ladder_price DECIMAL(14,2) NULL COMMENT '零售阶梯价',
            retail_tax DECIMAL(14,2) NULL COMMENT '零售税费',
            retail_shipping DECIMAL(14,2) NULL COMMENT '零售运费',
            shipping_origin VARCHAR(100) NULL COMMENT '发货地',
            shipping_time VARCHAR(100) NULL COMMENT '发货时间',
            warranty_time VARCHAR(100) NULL COMMENT '质保时间',
            daily_order_time VARCHAR(100) NULL COMMENT '每日结单时间',
            quote_time VARCHAR(100) NULL COMMENT '报价时间',
            expire_date VARCHAR(100) NULL COMMENT '报价有效期',
            is_default TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认规格组合',
            is_external_visible TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否对外展示：0否，1是',
            remark VARCHAR(500) NULL COMMENT '备注',
            update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '价格最后修改时间',
            PRIMARY KEY (id),
            UNIQUE KEY uq_variant_supplier (part_id, variant_group_id, supplier),
            KEY idx_variant_prices_part_group (part_id, variant_group_id),
            CONSTRAINT fk_variant_prices_part FOREIGN KEY (part_id) REFERENCES parts(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='产品规格组合价格表：保存供应商和对应的全部价格'"""
    )
    # 添加新字段（如果不存在）
    new_columns = [
        ("no_tax_price", "DECIMAL(14,2) NULL COMMENT '不含票单价'"),
        ("freight_remark", "VARCHAR(255) NULL COMMENT '运费备注'"),
        ("warranty_time", "VARCHAR(100) NULL COMMENT '质保时间'"),
        ("daily_order_time", "VARCHAR(100) NULL COMMENT '每日结单时间'"),
        ("quote_time", "VARCHAR(100) NULL COMMENT '报价时间'"),
        ("expire_date", "VARCHAR(100) NULL COMMENT '报价有效期'"),
        ("is_external_visible", "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否对外展示：0否，1是'"),
    ]
    for col_name, col_def in new_columns:
        try:
            cursor.execute(f"ALTER TABLE product_variant_prices ADD COLUMN {col_name} {col_def}")
        except:
            pass  # 列已存在

    # 旧数据库中这两个字段曾使用 DATE/DATETIME，但页面允许输入“30天”“现货”等业务文本。
    # 只在字段类型不一致时迁移，避免每次请求重复执行 ALTER TABLE。
    text_business_columns = [
        ("shipping_time", "VARCHAR(100) NULL COMMENT '发货时间（手动输入）'"),
        ("expire_date", "VARCHAR(100) NULL COMMENT '报价有效期（日期或文字说明）'"),
    ]
    for col_name, col_def in text_business_columns:
        cursor.execute("SHOW COLUMNS FROM product_variant_prices LIKE %s", (col_name,))
        column = cursor.fetchone()
        if column and str(column.get('Type', '')).lower() != 'varchar(100)':
            logger.info(f"[数据库迁移] product_variant_prices.{col_name} -> VARCHAR(100)")
            cursor.execute(f"ALTER TABLE product_variant_prices MODIFY COLUMN {col_name} {col_def}")
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS product_variant_group_specs (
            id BIGINT NOT NULL AUTO_INCREMENT COMMENT '组合规格关联ID',
            part_id INT NOT NULL COMMENT '产品主表ID，对应parts.id',
            variant_group_id VARCHAR(64) NOT NULL COMMENT '完整规格组合ID',
            spec_id BIGINT NOT NULL COMMENT '规格字典ID，对应product_variant_specs.id',
            sort_order INT NOT NULL DEFAULT 0 COMMENT '规格在组合中的显示顺序',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            PRIMARY KEY (id),
            UNIQUE KEY uq_variant_group_spec (part_id, variant_group_id, spec_id),
            KEY idx_variant_group_specs_group (part_id, variant_group_id),
            KEY idx_variant_group_specs_spec (spec_id),
            CONSTRAINT fk_variant_group_specs_part FOREIGN KEY (part_id) REFERENCES parts(id) ON DELETE CASCADE,
            CONSTRAINT fk_variant_group_specs_spec FOREIGN KEY (spec_id) REFERENCES product_variant_specs(id) ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='规格组合关联表：关联完整组合与规格字典值'"""
    )

    # 兼容旧的两表结构：旧表将规格字典与组合关系混在一起，会产生重复规格值。
    cursor.execute("SHOW COLUMNS FROM product_variant_specs LIKE 'variant_group_id'")
    if cursor.fetchone():
        cursor.execute(
            """INSERT IGNORE INTO product_variant_group_specs
                   (part_id, variant_group_id, spec_id, sort_order)
               SELECT old.part_id, old.variant_group_id, canonical.id, old.sort_order
               FROM product_variant_specs old
               JOIN product_variant_prices price
                 ON price.part_id = old.part_id AND price.variant_group_id = old.variant_group_id
               JOIN product_variant_specs canonical
                 ON canonical.id = (
                    SELECT MIN(s2.id) FROM product_variant_specs s2
                    WHERE s2.part_id = old.part_id
                      AND s2.spec_name = old.spec_name
                      AND s2.spec_value = old.spec_value
                 )"""
        )
        cursor.execute(
            """DELETE duplicate_row FROM product_variant_specs duplicate_row
               JOIN product_variant_specs canonical
                 ON canonical.part_id = duplicate_row.part_id
                AND canonical.spec_name = duplicate_row.spec_name
                AND canonical.spec_value = duplicate_row.spec_value
                AND canonical.id < duplicate_row.id"""
        )
        cursor.execute("ALTER TABLE product_variant_specs DROP INDEX uq_variant_spec_name")
        cursor.execute("ALTER TABLE product_variant_specs DROP INDEX idx_variant_specs_part_group")
        cursor.execute("ALTER TABLE product_variant_specs DROP COLUMN variant_group_id")
        cursor.execute("ALTER TABLE product_variant_specs ADD UNIQUE KEY uq_variant_spec_value (part_id, spec_name, spec_value)")
        cursor.execute("ALTER TABLE product_variant_specs ADD KEY idx_variant_specs_name (part_id, spec_name)")
        cursor.execute("ALTER TABLE product_variant_specs COMMENT='产品规格字典表：每个规格名和规格值只保存一次'")
        conn.commit()


# 字段中文名映射
FIELD_LABELS = {
    'id': 'ID',
    'sku_code': 'SKU编码',
    'product_name': '产品名称',
    'product_type': '产品分类',
    'product_brand': '产品品牌',
    'model': '型号',
    'supplier': '供应商',
    'warranty': '质保',
    'applicable_elevator_brand': '适用电梯品牌',
    'nature': '性质',
    'substitute_model': '替代型号',
    'precautions': '注意事项',
    'category': '品类归属',
    'technical_params': '技术参数',
    'purchase_cost': '采购成本价',
    'purchase_special_invoice': '进项专票',
    'purchase_general_invoice': '进项普票',
    'purchase_shipping': '采购运费',
    'retail_price': '零售价格',
    'retail_ladder_price': '零售阶梯价',
    'retail_tax': '零售税费',
    'retail_shipping': '零售运费',
    'remark': '备注',
    'daily_cutoff_time': '每日截单时间',
    'quote_validity': '报价有效期',
    'shipping_origin': '发货地',
    'shipping_time': '发货时间',
    'remark_2': '备注(2)',
    'updater': '更新人',
    'key_part_images': '关键部位图片',
    'actual_photos': '实物图照片',
    'product_image_3': '商品图片3',
    'product_image_4': '商品图片4',
    'product_image_5': '商品图片5',
    'product_image_6': '商品图片6',
    'product_image_7': '商品图片7',
    'product_image_8': '商品图片8',
    'product_image_9': '商品图片9',
    'product_image_10': '商品图片10',
    'product_detail_images': '商品详情图片',
    'filler': '填报人',
    'update_time': '更新时间',
    'filler_2': '填报人(2)',
    'update_time_2': '更新时间(2)',
    'filler_ip': '填报IP',
}

# 图片字段列表
IMAGE_FIELDS = [
    'key_part_images', 'actual_photos',
    'product_image_3', 'product_image_4', 'product_image_5',
    'product_image_6', 'product_image_7', 'product_image_8',
    'product_image_9', 'product_image_10', 'product_detail_images',
]

CREATE_PRODUCT_FIELDS = [
    'product_name', 'product_brand', 'model',
    'supplier', 'warranty', 'applicable_elevator_brand', 'nature',
    'substitute_model', 'precautions', 'product_type',
    'technical_params', 'remark', 'remark_2',
    'purchase_cost', 'purchase_special_invoice',
    'purchase_general_invoice', 'purchase_shipping',
] + IMAGE_FIELDS


def clean_image_urls(value):
    """清洗图片 URL：替换转义反斜杠、修复双斜杠"""
    if not value:
        return value
    # 替换 \/ 为 /
    cleaned = value.replace('\\/', '/')
    # 修复域名后的双斜杠（保留 :// 协议部分）
    import re
    cleaned = re.sub(r'(?<!:)//', '/', cleaned)
    return cleaned


def parse_image_urls(value):
    """兼容 JSON 数组、单个 URL 和历史逗号/换行分隔格式。"""
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        if isinstance(parsed, str) and parsed.strip():
            return [parsed.strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    import re
    return [item.strip() for item in re.split(r'[\r\n,]+', text) if item.strip()]


def qiniu_public_url(key):
    domain = QINIU_CONFIG['domain']
    if not domain.startswith(('http://', 'https://')):
        domain = 'https://' + domain
    return f"{domain}/{quote(key, safe='/')}"


def validate_qiniu_config():
    missing = [
        env_name for key, env_name in (
            ('access_key', 'QINIU_ACCESS_KEY'),
            ('secret_key', 'QINIU_SECRET_KEY'),
            ('bucket', 'QINIU_BUCKET'),
            ('domain', 'QINIU_DOMAIN'),
        )
        if not QINIU_CONFIG[key]
    ]
    if missing:
        raise HTTPException(
            status_code=503,
            detail='七牛云尚未配置，请先设置：' + '、'.join(missing),
        )

# 主要展示字段（中间区域优先显示的）
MAIN_FIELDS = [
    'sku_code', 'product_name', 'product_brand', 'model',
    'supplier', 'warranty', 'applicable_elevator_brand', 'nature',
    'substitute_model', 'precautions', 'category', 'technical_params',
    'purchase_cost', 'purchase_special_invoice', 'purchase_general_invoice',
    'purchase_shipping', 'retail_price', 'retail_ladder_price',
    'retail_tax', 'retail_shipping', 'remark', 'daily_cutoff_time',
    'quote_validity', 'shipping_origin', 'shipping_time', 'remark_2',
    'updater', 'filler', 'update_time', 'filler_2', 'update_time_2', 'filler_ip',
]
