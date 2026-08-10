from ..bootstrap import app, templates
from ..shared import *
from ..audit import display_change_value, write_operation_log

@app.get("/goods", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "field_labels": FIELD_LABELS
        }
    )


@app.get("/api/products")
async def list_products(
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    product_type: Optional[str] = None,
    classification_status: Optional[str] = None,
    feedback_status: Optional[str] = None,
    duplicates_only: bool = False,
    page: int = 1,
    page_size: int = 30,
):
    """获取产品列表（分页）"""
    logger.info(
        f"[查询] 产品列表 | page={page}, page_size={page_size}, keyword={keyword}, "
        f"category={category}, product_type={product_type}, classification_status={classification_status}, "
        f"feedback_status={feedback_status}, "
        f"duplicates_only={duplicates_only}"
    )
    conn = get_db()
    try:
        cursor = conn.cursor()
        ensure_duplicate_marks_table(conn)
        where = " WHERE 1=1"
        duplicate_group_join = ""
        params = []

        if keyword:
            where += " AND (parts.product_name LIKE %s OR parts.model LIKE %s OR parts.sku_code LIKE %s OR parts.product_brand LIKE %s)"
            like_kw = f"%{keyword}%"
            params.extend([like_kw, like_kw, like_kw, like_kw])

        if duplicates_only:
            duplicate_group_join = (
                " INNER JOIN ("
                "SELECT product_name, model FROM parts"
                " WHERE COALESCE(TRIM(product_name), '') <> ''"
                " AND COALESCE(TRIM(model), '') <> ''"
                " GROUP BY product_name, model HAVING COUNT(*) > 1"
                ") duplicate_group"
                " ON duplicate_group.product_name = parts.product_name"
                " AND duplicate_group.model = parts.model"
            )
            where += (
                " AND COALESCE(TRIM(parts.product_name), '') <> ''"
                " AND COALESCE(TRIM(parts.model), '') <> ''"
            )

        if category:
            where += " AND parts.category = %s"
            params.append(category)

        if product_type:
            if product_type not in PRODUCT_TYPE_VALUES:
                raise HTTPException(status_code=400, detail="无效的三级产品分类")
            where += " AND parts.product_type = %s"
            params.append(product_type)
        elif classification_status == "unclassified":
            placeholders = ", ".join(["%s"] * len(PRODUCT_TYPE_VALUES))
            where += f" AND (parts.product_type IS NULL OR TRIM(parts.product_type) = '' OR parts.product_type NOT IN ({placeholders}))"
            params.extend(PRODUCT_TYPE_VALUES)

        if feedback_status:
            normalized_feedback_status = feedback_status.strip().lower()
            if normalized_feedback_status != "pending":
                raise HTTPException(status_code=400, detail="目前只支持查询待处理反馈")
            where += (
                " AND EXISTS (SELECT 1 FROM sales_product_feedback feedback"
                " WHERE feedback.parts_id=parts.id AND feedback.status='pending')"
            )

        # 查总数
        count_sql = "SELECT COUNT(*) AS total FROM parts" + duplicate_group_join + where
        logger.debug(f"[SQL] {count_sql} | params={params}")
        cursor.execute(count_sql, params)
        total = cursor.fetchone()['total']

        # 查分页数据
        offset = (page - 1) * page_size
        duplicate_flag_sql = "1" if duplicates_only else \
            "CASE WHEN COALESCE(TRIM(parts.product_name), '') <> '' AND COALESCE(TRIM(parts.model), '') <> '' " \
            "AND EXISTS (SELECT 1 FROM parts p2 WHERE p2.product_name = parts.product_name " \
            "AND p2.model = parts.model AND p2.id <> parts.id) THEN 1 ELSE 0 END"
        sql = "SELECT parts.id, parts.sku_code, parts.product_name, parts.model, parts.product_brand, parts.category, parts.product_type, parts.update_time_2, " \
              "(SELECT COUNT(*) FROM sales_product_feedback feedback WHERE feedback.parts_id=parts.id AND feedback.status='pending') AS pending_feedback_count, " \
              + duplicate_flag_sql + " AS is_duplicate, " \
              "CASE WHEN dpm.id IS NULL THEN 0 ELSE 1 END AS duplicate_marked " \
              "FROM parts" + duplicate_group_join + \
              " LEFT JOIN duplicate_product_marks dpm ON dpm.product_id = parts.id" + where
        if duplicates_only:
            sql += " ORDER BY parts.product_name, parts.model, parts.id"
        else:
            sql += " ORDER BY parts.id"
        sql += " LIMIT %s OFFSET %s"
        params.extend([page_size, offset])
        logger.debug(f"[SQL] {sql} | params={params}")
        cursor.execute(sql, params)
        items = cursor.fetchall()

        logger.info(f"[查询] 产品列表完成 | 返回 {len(items)} 条, 总计 {total} 条")
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        logger.error(f"[查询] 产品列表失败 | error={e}")
        raise
    finally:
        conn.close()


@app.get("/api/products/{product_id}")
async def get_product(product_id: int):
    """获取单个产品完整详情"""
    logger.info(f"[查询] 产品详情 | product_id={product_id}")
    conn = get_db()
    try:
        cursor = conn.cursor()
        sql = "SELECT * FROM parts WHERE id = %s"
        logger.debug(f"[SQL] {sql} | params=({product_id},)")
        cursor.execute(sql, (product_id,))
        row = cursor.fetchone()
        if not row:
            logger.warning(f"[查询] 产品不存在 | product_id={product_id}")
            raise HTTPException(status_code=404, detail="产品不存在")
        cursor.execute(
            """SELECT
                   MAX(CASE WHEN operation_type='COMPLETE' THEN id END) AS complete_id,
                   MAX(CASE WHEN operation_type IN ('CREATE','UPDATE') THEN id END) AS change_id
               FROM employee_operation_logs
               WHERE part_id=%s""",
            (product_id,),
        )
        completion = cursor.fetchone() or {}
        complete_id = int(completion.get("complete_id") or 0)
        change_id = int(completion.get("change_id") or 0)
        row["modification_completed"] = complete_id > change_id
        row["modification_completed_at"] = None
        row["modification_completed_by"] = ""
        if row["modification_completed"]:
            cursor.execute(
                """SELECT log.created_at,
                          COALESCE(NULLIF(user.nickname,''), user.username,
                                   CONCAT('用户', log.user_id)) AS operator_name
                   FROM employee_operation_logs log
                   LEFT JOIN yh_admin_user user ON user.id=log.user_id
                   WHERE log.id=%s""",
                (complete_id,),
            )
            completed_log = cursor.fetchone() or {}
            row["modification_completed_at"] = completed_log.get("created_at")
            row["modification_completed_by"] = completed_log.get("operator_name") or ""
        logger.info(f"[查询] 产品详情完成 | product_id={product_id}, name={row.get('product_name', 'N/A')}")
        return row
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[查询] 产品详情失败 | product_id={product_id}, error={e}")
        raise
    finally:
        conn.close()


@app.post("/api/products/{product_id}/complete-modification")
async def complete_product_modification(product_id: int):
    """切换当前产品本轮修改是否完成。"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, product_name, model FROM parts WHERE id=%s FOR UPDATE",
            (product_id,),
        )
        product = cursor.fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="产品不存在")
        cursor.execute(
            """SELECT
                   MAX(CASE WHEN operation_type='COMPLETE' THEN id END) AS complete_id,
                   MAX(CASE WHEN operation_type IN ('CREATE','UPDATE') THEN id END) AS change_id
               FROM employee_operation_logs
               WHERE part_id=%s""",
            (product_id,),
        )
        state = cursor.fetchone() or {}
        complete_id = int(state.get("complete_id") or 0)
        change_id = int(state.get("change_id") or 0)
        if complete_id > change_id:
            cursor.execute(
                "DELETE FROM employee_operation_logs WHERE part_id=%s AND operation_type='COMPLETE'",
                (product_id,),
            )
            conn.commit()
            logger.info("[撤销修改完成] product_id=%s", product_id)
            return {"message": "已撤销修改完成标记", "completed": False}
        write_operation_log(
            cursor,
            part_id=product_id,
            operation_type="COMPLETE",
            module_code="WORKFLOW",
            detail="标记产品修改完成",
            product_name=product.get("product_name"),
            model=product.get("model"),
        )
        conn.commit()
        logger.info("[修改完成] product_id=%s", product_id)
        return {"message": "已标记修改完成", "completed": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.delete("/api/products/{product_id}")
async def delete_product(product_id: int):
    """根据产品ID删除 parts 主数据；规格、组合和供应商价格由外键级联删除。"""
    logger.info(f"[删除产品] 开始 | product_id={product_id}")
    conn = get_db()
    try:
        ensure_duplicate_marks_table(conn)
        ensure_employee_operation_logs_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, product_name, model FROM parts WHERE id = %s FOR UPDATE",
            (product_id,),
        )
        product = cursor.fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="产品不存在或已被删除")

        # duplicate_product_marks 没有外键，需要主动清理，避免遗留孤立标记。
        cursor.execute(
            "DELETE FROM duplicate_product_marks WHERE product_id = %s",
            (product_id,),
        )
        cursor.execute("DELETE FROM parts WHERE id = %s", (product_id,))
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="产品不存在或已被删除")
        write_operation_log(
            cursor,
            part_id=product_id,
            product_name=product.get("product_name"),
            model=product.get("model"),
            operation_type="DELETE",
            module_code="PRODUCT",
            detail=(
                f"删除产品；产品名称：{display_change_value(product.get('product_name'))}；"
                f"型号：{display_change_value(product.get('model'))}"
            ),
        )
        conn.commit()
        logger.info(
            f"[删除产品] 完成 | product_id={product_id}, "
            f"name={product.get('product_name')}, model={product.get('model')}"
        )
        return {
            "message": "产品删除成功",
            "deleted_id": product_id,
            "product_name": product.get("product_name"),
            "model": product.get("model"),
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"[删除产品] 失败 | product_id={product_id}, error={e}")
        raise
    finally:
        conn.close()


class DuplicateMarkRequest(BaseModel):
    marked_by: Optional[str] = "当前员工"


@app.post("/api/products/{product_id}/duplicate-mark")
async def mark_duplicate_product(product_id: int, req: DuplicateMarkRequest):
    """记录员工确认的重复产品，幂等写入，不提供删除动作。"""
    conn = get_db()
    try:
        ensure_duplicate_marks_table(conn)
        ensure_employee_operation_logs_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT product_name, model FROM parts WHERE id = %s", (product_id,))
        product = cursor.fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="产品不存在")
        marker = (req.marked_by or "当前员工").strip()[:100] or "当前员工"
        cursor.execute(
            """INSERT INTO duplicate_product_marks (product_id, product_name, model, marked_by)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE product_name = VALUES(product_name), model = VALUES(model)""",
            (product_id, product['product_name'], product['model'], marker),
        )
        write_operation_log(
            cursor,
            part_id=product_id,
            operation_type="UPDATE",
            module_code="PRODUCT",
            detail="标记为重复产品，等待后续统一处理",
        )
        conn.commit()
        cursor.execute("SELECT id, marked_by, marked_at FROM duplicate_product_marks WHERE product_id = %s", (product_id,))
        mark = cursor.fetchone()
        return {"message": "已标记为待删除", "marked": True, "mark": mark}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"[重复标记] 保存失败 | product_id={product_id}, error={e}")
        raise
    finally:
        conn.close()


@app.delete("/api/products/{product_id}/duplicate-mark")
async def unmark_duplicate_product(product_id: int):
    """取消员工标记的重复产品"""
    conn = get_db()
    try:
        ensure_duplicate_marks_table(conn)
        ensure_employee_operation_logs_table(conn)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM duplicate_product_marks WHERE product_id = %s", (product_id,))
        if cursor.rowcount:
            write_operation_log(
                cursor,
                part_id=product_id,
                operation_type="UPDATE",
                module_code="PRODUCT",
                detail="取消重复产品标记",
            )
        conn.commit()
        logger.info(f"[重复标记] 取消标记 | product_id={product_id}")
        return {"message": "已取消标记", "marked": False}
    except Exception as e:
        conn.rollback()
        logger.error(f"[重复标记] 取消失败 | product_id={product_id}, error={e}")
        raise
    finally:
        conn.close()


class UpdateFieldRequest(BaseModel):
    field: str
    value: Optional[str] = None


class ProductCreateRequest(BaseModel):
    fields: Dict[str, Optional[str]]


class UpdateImagesRequest(BaseModel):
    """一次移动图片时同时更新来源和目标图片字段。"""
    fields: Dict[str, Optional[str]]


@app.post("/api/products")
async def create_product(req: ProductCreateRequest):
    """只新增 parts 主表数据，不创建规格、规格组合或供应商价格记录。"""
    invalid_fields = [field for field in req.fields if field not in CREATE_PRODUCT_FIELDS]
    if invalid_fields:
        raise HTTPException(status_code=400, detail=f"不支持新增字段：{', '.join(invalid_fields)}")

    values = {
        field: (str(value).strip() if value is not None else None)
        for field, value in req.fields.items()
        if field in CREATE_PRODUCT_FIELDS
    }
    values = {field: (value if value else None) for field, value in values.items()}
    for image_field in IMAGE_FIELDS:
        if values.get(image_field):
            values[image_field] = clean_image_urls(values[image_field])
    if values.get('product_type') and values['product_type'] not in PRODUCT_TYPE_VALUES:
        raise HTTPException(status_code=400, detail="产品分类必须选择分类树中的三级分类")

    conn = get_db()
    try:
        ensure_employee_operation_logs_table(conn)
        cursor = conn.cursor()
        fields = list(values.keys())
        if fields:
            placeholders = ', '.join(['%s'] * len(fields))
            field_sql = ', '.join(f"`{field}`" for field in fields)
            cursor.execute(
                f"INSERT INTO parts ({field_sql}, update_time_2) VALUES ({placeholders}, CURRENT_TIMESTAMP)",
                [values[field] for field in fields],
            )
        else:
            cursor.execute(
                "INSERT INTO parts (update_time_2) VALUES (CURRENT_TIMESTAMP)"
            )
        product_id = cursor.lastrowid
        write_operation_log(
            cursor,
            part_id=product_id,
            operation_type="CREATE",
            module_code="PRODUCT",
            detail=(
                f"新增产品；产品名称：{display_change_value(values.get('product_name'))}；"
                f"型号：{display_change_value(values.get('model'))}"
            ),
        )
        conn.commit()
        cursor.execute("SELECT * FROM parts WHERE id = %s", (product_id,))
        product = cursor.fetchone()
        logger.info(f"[新增产品] 完成 | product_id={product_id}, name={values.get('product_name')}")
        return {"message": "产品新增成功", "product": product}
    except Exception as e:
        conn.rollback()
        logger.error(f"[新增产品] 失败 | error={e}")
        raise
    finally:
        conn.close()


class ClassificationCreateRequest(BaseModel):
    level: str
    first_level: str
    second_level: Optional[str] = None
    name: str


class ClassificationEditRequest(BaseModel):
    level: str
    first_level: str
    second_level: Optional[str] = None
    name: str
    new_name: str


class ClassificationDeleteRequest(BaseModel):
    level: str
    first_level: str
    second_level: Optional[str] = None
    name: str


@app.put("/api/products/{product_id}")
async def update_product(product_id: int, req: UpdateFieldRequest):
    """更新产品的某个字段"""
    field_label = FIELD_LABELS.get(req.field, req.field)
    logger.info(f"[修改] 开始 | product_id={product_id}, field={req.field}({field_label}), value={req.value}")

    if req.field not in FIELD_LABELS or req.field == 'id':
        logger.warning(f"[修改] 拒绝非法字段 | field={req.field}")
        raise HTTPException(status_code=400, detail=f"不支持修改字段: {req.field}")

    if req.field == 'update_time_2':
        raise HTTPException(status_code=400, detail="更新时间由系统自动维护")

    if req.field == 'product_type' and req.value and req.value not in PRODUCT_TYPE_VALUES:
        raise HTTPException(status_code=400, detail="产品分类必须选择 Excel 方案中的三级分类")

    # 图片字段自动清洗 URL
    value_to_save = req.value
    if req.field in IMAGE_FIELDS and req.value:
        value_to_save = clean_image_urls(req.value)
        if value_to_save != req.value:
            logger.info(f"[清洗] 图片URL已自动修复 | field={req.field}")

    conn = get_db()
    try:
        ensure_employee_operation_logs_table(conn)
        cursor = conn.cursor()
        # 先查旧值
        cursor.execute("SELECT `%s` FROM parts WHERE id = %%s" % req.field, (product_id,))
        old_row = cursor.fetchone()
        if not old_row:
            logger.warning(f"[修改] 产品不存在 | product_id={product_id}")
            raise HTTPException(status_code=404, detail="产品不存在")
        old_value = old_row.get(req.field, None)

        sql = f"UPDATE parts SET `{req.field}` = %s, update_time_2 = CURRENT_TIMESTAMP WHERE id = %s"
        logger.debug(f"[SQL] {sql} | params=({value_to_save}, {product_id})")
        cursor.execute(sql, (value_to_save, product_id))
        if old_value != value_to_save:
            module_code = (
                "IMAGE"
                if req.field in IMAGE_FIELDS
                else "CLASSIFICATION"
                if req.field == "product_type"
                else "PRODUCT"
            )
            write_operation_log(
                cursor,
                part_id=product_id,
                operation_type="UPDATE",
                module_code=module_code,
                detail=(
                    f"修改{field_label}："
                    f"{display_change_value(old_value)} → {display_change_value(value_to_save)}"
                ),
            )
        conn.commit()

        logger.info(f"[修改] 完成 | product_id={product_id}, field={field_label}, "
                     f"old_value={old_value}, new_value={value_to_save}")
        cursor.execute("SELECT update_time_2 FROM parts WHERE id = %s", (product_id,))
        updated_at = cursor.fetchone()['update_time_2']
        return {"message": "更新成功", "field": req.field, "value": value_to_save, "update_time_2": updated_at}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[修改] 失败 | product_id={product_id}, field={req.field}, error={e}")
        raise
    finally:
        conn.close()


@app.put("/api/products/{product_id}/images")
async def update_product_images(product_id: int, req: UpdateImagesRequest):
    """原子更新多个图片字段，用于图片类型之间的拖放移动。"""
    invalid_fields = [field for field in req.fields if field not in IMAGE_FIELDS]
    if not req.fields or invalid_fields:
        raise HTTPException(status_code=400, detail="只支持更新产品图片字段")

    conn = get_db()
    try:
        ensure_employee_operation_logs_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM parts WHERE id = %s", (product_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="产品不存在")
        for field, value in req.fields.items():
            value_to_save = clean_image_urls(value) if value else value
            cursor.execute(f"UPDATE parts SET `{field}` = %s WHERE id = %s", (value_to_save, product_id))
        write_operation_log(
            cursor,
            part_id=product_id,
            operation_type="UPDATE",
            module_code="IMAGE",
            detail=(
                "调整图片资料；图片类型："
                + "、".join(FIELD_LABELS.get(field, field) for field in req.fields)
            ),
        )
        cursor.execute("UPDATE parts SET update_time_2 = CURRENT_TIMESTAMP WHERE id = %s", (product_id,))
        conn.commit()
        cursor.execute("SELECT update_time_2 FROM parts WHERE id = %s", (product_id,))
        updated_at = cursor.fetchone()['update_time_2']
        return {"message": "图片分类已更新", "fields": req.fields, "update_time_2": updated_at}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"[图片拖放] 更新失败 | product_id={product_id}, error={e}")
        raise
    finally:
        conn.close()


@app.get("/api/image-upload/config")
async def image_upload_config():
    """供页面判断七牛云是否可用，不返回任何密钥。"""
    return {
        "configured": all(QINIU_CONFIG.values()),
        "domain": QINIU_CONFIG['domain'] or None,
        "max_file_size_mb": MAX_UPLOAD_IMAGE_SIZE // 1024 // 1024,
        "max_file_count": MAX_UPLOAD_IMAGE_COUNT,
    }


@app.post("/api/products/{product_id}/images/upload")
async def upload_product_images(
    product_id: int,
    image_field: str = Form(...),
    files: List[UploadFile] = File(...),
):
    """上传本地图片到七牛云，并将云端 URL 追加写入 parts 对应图片字段。"""
    if image_field not in IMAGE_FIELDS:
        raise HTTPException(status_code=400, detail="无效的图片类型")
    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的图片")
    if len(files) > MAX_UPLOAD_IMAGE_COUNT:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {MAX_UPLOAD_IMAGE_COUNT} 张图片")
    validate_qiniu_config()

    conn = get_db()
    uploaded_urls = []
    try:
        ensure_employee_operation_logs_table(conn)
        cursor = conn.cursor()
        cursor.execute(f"SELECT `{image_field}` FROM parts WHERE id = %s", (product_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="产品不存在")

        auth = Auth(QINIU_CONFIG['access_key'], QINIU_CONFIG['secret_key'])
        for upload in files:
            content_type = (upload.content_type or '').lower()
            if content_type not in ALLOWED_IMAGE_MIME_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"{upload.filename or '文件'} 格式不支持，仅支持 JPG、PNG、GIF、WebP、BMP",
                )
            content = await upload.read(MAX_UPLOAD_IMAGE_SIZE + 1)
            if len(content) > MAX_UPLOAD_IMAGE_SIZE:
                raise HTTPException(status_code=400, detail=f"{upload.filename or '图片'} 超过 10MB")
            if not content:
                raise HTTPException(status_code=400, detail=f"{upload.filename or '图片'} 内容为空")

            extension = ALLOWED_IMAGE_MIME_TYPES.get(content_type) or mimetypes.guess_extension(content_type) or '.jpg'
            key = f"{datetime.now():%Y%m%d}/{uuid.uuid4().hex}{extension}"
            token = auth.upload_token(QINIU_CONFIG['bucket'], key, 3600)
            result, info = put_data(
                token,
                key,
                content,
                mime_type=content_type,
                check_crc=True,
            )
            if not result or result.get('key') != key:
                qiniu_error = getattr(info, 'text_body', None) or getattr(info, 'error', None) or '未知错误'
                raise HTTPException(status_code=502, detail=f"七牛云上传失败：{qiniu_error}")
            uploaded_urls.append(qiniu_public_url(key))

        urls = parse_image_urls(row.get(image_field))
        for url in uploaded_urls:
            if url not in urls:
                urls.append(url)
        value = json.dumps(urls, ensure_ascii=False)
        cursor.execute(
            f"UPDATE parts SET `{image_field}` = %s, update_time_2 = CURRENT_TIMESTAMP WHERE id = %s",
            (value, product_id),
        )
        write_operation_log(
            cursor,
            part_id=product_id,
            operation_type="UPDATE",
            module_code="IMAGE",
            detail=(
                f"上传图片；图片类型：{FIELD_LABELS.get(image_field, image_field)}；"
                f"新增数量：{len(uploaded_urls)}"
            ),
        )
        conn.commit()
        cursor.execute("SELECT update_time_2 FROM parts WHERE id = %s", (product_id,))
        updated_at = cursor.fetchone()['update_time_2']
        logger.info(
            f"[七牛上传] 完成 | product_id={product_id}, field={image_field}, count={len(uploaded_urls)}"
        )
        return {
            "message": f"已上传 {len(uploaded_urls)} 张图片",
            "field": image_field,
            "urls": uploaded_urls,
            "value": value,
            "update_time_2": updated_at,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"[七牛上传] 失败 | product_id={product_id}, field={image_field}, error={e}")
        raise HTTPException(status_code=502, detail=f"图片上传失败：{e}")
    finally:
        for upload in files:
            await upload.close()
        conn.close()
