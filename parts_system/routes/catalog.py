from ..bootstrap import app, templates
from ..shared import *
from ..audit import write_operation_log

from .products import ClassificationCreateRequest, ClassificationEditRequest, ClassificationDeleteRequest

@app.get("/api/categories")
async def list_categories():
    """获取所有品类列表"""
    logger.info("[查询] 品类列表")
    conn = get_db()
    try:
        cursor = conn.cursor()
        sql = "SELECT DISTINCT category FROM parts WHERE category IS NOT NULL ORDER BY category"
        logger.debug(f"[SQL] {sql}")
        cursor.execute(sql)
        rows = cursor.fetchall()
        result = [r['category'] for r in rows]
        logger.info(f"[查询] 品类列表完成 | 共 {len(result)} 个品类")
        return result
    except Exception as e:
        logger.error(f"[查询] 品类列表失败 | error={e}")
        raise
    finally:
        conn.close()


@app.get("/api/suppliers")
async def list_suppliers():
    """获取所有去重后的供应商名称列表"""
    logger.info("[查询] 供应商列表")
    conn = get_db()
    try:
        cursor = conn.cursor()
        # 分别从 parts 与 product_variant_prices 取供应商，Python 层合并去重，
        # 避免两表 supplier 列 collation 不同导致 UNION 报错
        cursor.execute("SELECT DISTINCT supplier FROM parts WHERE supplier IS NOT NULL AND supplier != ''")
        rows_parts = cursor.fetchall()
        cursor.execute("SELECT DISTINCT supplier FROM product_variant_prices WHERE supplier IS NOT NULL AND supplier != ''")
        rows_prices = cursor.fetchall()
        result = sorted({r['supplier'] for r in rows_parts} | {r['supplier'] for r in rows_prices})
        logger.info(f"[查询] 供应商列表完成 | 共 {len(result)} 个供应商")
        return result
    except Exception as e:
        logger.error(f"[查询] 供应商列表失败 | error={e}")
        raise
    finally:
        conn.close()


@app.get("/api/product-classifications")
async def list_product_classifications():
    """获取 Excel 方案中的三级产品分类树及各三级分类的产品数量。"""
    logger.info("[查询] 产品分类树")
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT product_type, COUNT(*) AS count FROM parts GROUP BY product_type"
        )
        rows = cursor.fetchall()
        raw_counts = {row['product_type']: row['count'] for row in rows}
        counts = {value: raw_counts.get(value, 0) for value in PRODUCT_TYPE_VALUES}
        unclassified_count = sum(
            count for value, count in raw_counts.items()
            if not value or value not in PRODUCT_TYPE_VALUES
        )
        cursor.execute(
            """SELECT COUNT(DISTINCT parts_id) AS count
               FROM sales_product_feedback
               WHERE status='pending' AND parts_id IS NOT NULL"""
        )
        correction_count = cursor.fetchone()["count"]
        return {
            "tree": PRODUCT_CLASSIFICATION_TREE,
            "values": PRODUCT_TYPE_VALUES,
            "counts": counts,
            "unclassified_count": unclassified_count,
            "correction_count": correction_count,
        }
    except Exception as e:
        logger.error(f"[查询] 产品分类树失败 | error={e}")
        raise
    finally:
        conn.close()


@app.post("/api/product-classifications")
async def create_product_classification(req: ClassificationCreateRequest):
    """新增二级或三级分类，并保存到本地分类方案文件。"""
    name = req.name.strip()
    first_name = req.first_level.strip()
    second_name = (req.second_level or '').strip()
    if req.level not in ('second', 'third') or not name or not first_name:
        raise HTTPException(status_code=400, detail="分类参数不完整")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="分类名称不能超过100个字符")

    first = next((item for item in PRODUCT_CLASSIFICATION_TREE if item['name'] == first_name), None)
    if not first:
        raise HTTPException(status_code=404, detail="一级分类不存在")

    if req.level == 'second':
        if any(item['name'] == name for item in first['children']):
            raise HTTPException(status_code=409, detail="该二级分类已存在")
        first['children'].append({'name': name, 'children': []})
    else:
        if not second_name:
            raise HTTPException(status_code=400, detail="新增三级分类必须指定二级分类")
        second = next((item for item in first['children'] if item['name'] == second_name), None)
        if not second:
            raise HTTPException(status_code=404, detail="二级分类不存在")
        if name in PRODUCT_TYPE_VALUES:
            raise HTTPException(status_code=409, detail="该三级产品分类已存在")
        second['children'].append(name)

    refresh_product_type_values()
    try:
        save_classification_tree()
    except Exception as e:
        logger.error(f"[分类树] 保存分类失败 | error={e}")
        raise HTTPException(status_code=500, detail="分类保存失败")
    return {"message": "分类新增成功", "tree": PRODUCT_CLASSIFICATION_TREE, "values": PRODUCT_TYPE_VALUES}


@app.patch("/api/product-classifications")
async def edit_product_classification(req: ClassificationEditRequest):
    """编辑一级、二级或三级分类；三级改名会同步已有产品的 product_type。"""
    old_name = req.name.strip()
    new_name = req.new_name.strip()
    first_name = req.first_level.strip()
    second_name = (req.second_level or '').strip()
    if req.level not in ('first', 'second', 'third') or not old_name or not new_name:
        raise HTTPException(status_code=400, detail="分类编辑参数不完整")
    if len(new_name) > 100:
        raise HTTPException(status_code=400, detail="分类名称不能超过100个字符")

    first = next((item for item in PRODUCT_CLASSIFICATION_TREE if item['name'] == first_name), None)
    if not first:
        raise HTTPException(status_code=404, detail="一级分类不存在")

    if req.level == 'first':
        target = first
        if target['name'] != old_name:
            raise HTTPException(status_code=404, detail="一级分类不存在")
        if any(item is not target and item['name'] == new_name for item in PRODUCT_CLASSIFICATION_TREE):
            raise HTTPException(status_code=409, detail="该一级分类名称已存在")
        target['name'] = new_name
    elif req.level == 'second':
        target = next((item for item in first['children'] if item['name'] == old_name), None)
        if not target:
            raise HTTPException(status_code=404, detail="二级分类不存在")
        if any(item is not target and item['name'] == new_name for item in first['children']):
            raise HTTPException(status_code=409, detail="该二级分类名称已存在")
        target['name'] = new_name
    else:
        second = next((item for item in first['children'] if item['name'] == second_name), None)
        if not second:
            raise HTTPException(status_code=404, detail="二级分类不存在")
        if old_name not in second['children']:
            raise HTTPException(status_code=404, detail="三级分类不存在")
        if new_name != old_name and new_name in PRODUCT_TYPE_VALUES:
            raise HTTPException(status_code=409, detail="该三级产品分类名称已存在")
        conn = get_db()
        try:
            cursor = conn.cursor()
            ensure_employee_operation_logs_table(conn)
            cursor.execute(
                "SELECT id FROM parts WHERE product_type = %s",
                (old_name,),
            )
            affected_products = cursor.fetchall()
            cursor.execute("UPDATE parts SET product_type = %s WHERE product_type = %s", (new_name, old_name))
            for product in affected_products:
                write_operation_log(
                    cursor,
                    part_id=product["id"],
                    operation_type="UPDATE",
                    module_code="CLASSIFICATION",
                    detail=f"产品分类批量改名：{old_name} → {new_name}",
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        second['children'][second['children'].index(old_name)] = new_name

    refresh_product_type_values()
    try:
        save_classification_tree()
    except Exception as e:
        logger.error(f"[分类树] 保存编辑失败 | error={e}")
        raise HTTPException(status_code=500, detail="分类编辑保存失败")
    return {"message": "分类编辑成功", "tree": PRODUCT_CLASSIFICATION_TREE, "values": PRODUCT_TYPE_VALUES}


@app.delete("/api/product-classifications")
async def delete_product_classification(req: ClassificationDeleteRequest):
    """删除一级、二级或三级分类；删除一级会级联删除子分类，删除三级会清空对应产品的 product_type。"""
    first_name = req.first_level.strip()
    second_name = (req.second_level or '').strip()
    name = req.name.strip()
    if req.level not in ('first', 'second', 'third') or not name or not first_name:
        raise HTTPException(status_code=400, detail="分类删除参数不完整")

    first = next((item for item in PRODUCT_CLASSIFICATION_TREE if item['name'] == first_name), None)
    if not first:
        raise HTTPException(status_code=404, detail="一级分类不存在")

    if req.level == 'first':
        if first['name'] != name:
            raise HTTPException(status_code=404, detail="一级分类不存在")
        # 收集所有三级分类名，清空对应产品的 product_type
        all_third = [t for s in first['children'] for t in s['children']]
        PRODUCT_CLASSIFICATION_TREE.remove(first)
        if all_third:
            conn = get_db()
            try:
                cursor = conn.cursor()
                ensure_employee_operation_logs_table(conn)
                placeholders = ','.join(['%s'] * len(all_third))
                cursor.execute(
                    f"SELECT id, product_type FROM parts WHERE product_type IN ({placeholders})",
                    all_third,
                )
                affected_products = cursor.fetchall()
                cursor.execute(f"UPDATE parts SET product_type = NULL WHERE product_type IN ({placeholders})", all_third)
                for product in affected_products:
                    write_operation_log(
                        cursor,
                        part_id=product["id"],
                        operation_type="UPDATE",
                        module_code="CLASSIFICATION",
                        detail=f"删除一级分类后清空产品分类：{product['product_type']} → 空",
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    elif req.level == 'second':
        second = next((item for item in first['children'] if item['name'] == name), None)
        if not second:
            raise HTTPException(status_code=404, detail="二级分类不存在")
        third_names = second['children']
        first['children'].remove(second)
        if third_names:
            conn = get_db()
            try:
                cursor = conn.cursor()
                ensure_employee_operation_logs_table(conn)
                placeholders = ','.join(['%s'] * len(third_names))
                cursor.execute(
                    f"SELECT id, product_type FROM parts WHERE product_type IN ({placeholders})",
                    third_names,
                )
                affected_products = cursor.fetchall()
                cursor.execute(f"UPDATE parts SET product_type = NULL WHERE product_type IN ({placeholders})", third_names)
                for product in affected_products:
                    write_operation_log(
                        cursor,
                        part_id=product["id"],
                        operation_type="UPDATE",
                        module_code="CLASSIFICATION",
                        detail=f"删除二级分类后清空产品分类：{product['product_type']} → 空",
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    else:  # third
        second = next((item for item in first['children'] if item['name'] == second_name), None)
        if not second:
            raise HTTPException(status_code=404, detail="二级分类不存在")
        if name not in second['children']:
            raise HTTPException(status_code=404, detail="三级分类不存在")
        second['children'].remove(name)
        conn = get_db()
        try:
            cursor = conn.cursor()
            ensure_employee_operation_logs_table(conn)
            cursor.execute(
                "SELECT id FROM parts WHERE product_type = %s",
                (name,),
            )
            affected_products = cursor.fetchall()
            cursor.execute("UPDATE parts SET product_type = NULL WHERE product_type = %s", (name,))
            for product in affected_products:
                write_operation_log(
                    cursor,
                    part_id=product["id"],
                    operation_type="UPDATE",
                    module_code="CLASSIFICATION",
                    detail=f"删除三级分类后清空产品分类：{name} → 空",
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    refresh_product_type_values()
    try:
        save_classification_tree()
    except Exception as e:
        logger.error(f"[分类树] 保存删除失败 | error={e}")
        raise HTTPException(status_code=500, detail="分类删除保存失败")
    logger.info(f"[分类树] 删除分类 | level={req.level}, first={first_name}, second={second_name}, name={name}")
    return {"message": "分类删除成功", "tree": PRODUCT_CLASSIFICATION_TREE}


@app.get("/api/field-labels")
async def get_field_labels():
    """获取字段名中文映射"""
    logger.debug("[查询] 字段标签映射")
    return FIELD_LABELS
