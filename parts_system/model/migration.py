"""数据库迁移：建表、加列、数据修复等惰性迁移逻辑。"""

from ..config import logger


def ensure_employee_operation_logs_table(conn):
    """创建员工操作日志表，并修复历史数据快照。"""
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
    cursor.execute(
        """UPDATE employee_operation_logs l
           JOIN parts p ON p.id=l.part_id
           SET l.product_name_snapshot=COALESCE(l.product_name_snapshot,p.product_name),
               l.model_snapshot=COALESCE(l.model_snapshot,p.model)
           WHERE l.product_name_snapshot IS NULL OR l.model_snapshot IS NULL"""
    )
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
    if column and str(column.get("Type", "")).lower() != "text":
        logger.info("[数据库迁移] parts.technical_params -> TEXT")
        cursor.execute("ALTER TABLE parts MODIFY COLUMN technical_params TEXT NULL COMMENT '技术参数（多行文本）'")
    for col_name, col_def in [
        ("display_price_min", "DECIMAL(14,2) NULL COMMENT '所有规格组合对外展示价中的最低价'"),
        ("display_price_max", "DECIMAL(14,2) NULL COMMENT '所有规格组合对外展示价中的最高价'"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE parts ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass  # 列已存在


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
    if rule_table and rule_table.get("table_collation") != "utf8mb4_unicode_ci":
        logger.info("[数据库迁移] product_spec_required_rules -> utf8mb4_unicode_ci")
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
            product_name_column.get("column_default") != ""
            or product_name_column.get("column_comment") != expected_comment
        )
    ):
        logger.info("[数据库迁移] product_spec_required_rules.product_name 支持分类级规则")
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
        logger.info("[数据库迁移] product_spec_required_rules 新增产品名称匹配方式")
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
    expected_index_columns = "product_type,product_name,product_name_match_mode,spec_name"
    if unique_index and unique_index.get("index_columns") != expected_index_columns:
        logger.info("[数据库迁移] product_spec_required_rules 更新规则唯一索引")
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
            product_type_column.get("column_default") != ""
            or product_type_column.get("column_comment") != expected_type_comment
        )
    ):
        logger.info("[数据库迁移] product_spec_required_rules.product_type 支持名称级规则")
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
    new_columns = [
        ("no_tax_price", "DECIMAL(14,2) NULL COMMENT '不含票单价'"),
        ("freight_remark", "VARCHAR(255) NULL COMMENT '运费备注'"),
        ("warranty_time", "VARCHAR(100) NULL COMMENT '质保时间'"),
        ("daily_order_time", "VARCHAR(100) NULL COMMENT '每日结单时间'"),
        ("quote_time", "VARCHAR(100) NULL COMMENT '报价时间'"),
        ("expire_date", "VARCHAR(100) NULL COMMENT '报价有效期'"),
        ("is_external_visible", "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否对外展示：0否，1是（旧逻辑，后续删除）'"),
        ("oa_supplier_id", "BIGINT(20) NULL COMMENT 'OA供应商ID，对应oa_yixiuti.yh_supplier.id'"),
        ("external_price_fields", "SET('no_tax','special','general') NULL COMMENT '员工选择的对外展示价格字段'"),
    ]
    for col_name, col_def in new_columns:
        try:
            cursor.execute(f"ALTER TABLE product_variant_prices ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass  # 列已存在
    # 删除统一价字段 purchase_cost（已废弃）
    cursor.execute("SHOW COLUMNS FROM product_variant_prices LIKE 'purchase_cost'")
    if cursor.fetchone():
        logger.info("[数据库迁移] product_variant_prices 删除 purchase_cost 字段")
        cursor.execute("ALTER TABLE product_variant_prices DROP COLUMN purchase_cost")
    text_business_columns = [
        ("shipping_time", "VARCHAR(100) NULL COMMENT '发货时间（手动输入）'"),
        ("expire_date", "VARCHAR(100) NULL COMMENT '报价有效期（日期或文字说明）'"),
    ]
    for col_name, col_def in text_business_columns:
        cursor.execute("SHOW COLUMNS FROM product_variant_prices LIKE %s", (col_name,))
        column = cursor.fetchone()
        if column and str(column.get("Type", "")).lower() != "varchar(100)":
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
