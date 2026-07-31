from ..bootstrap import app, templates
from ..shared import *

# ========== 技术参数表 CRUD ==========

class ParamCreateRequest(BaseModel):
    param_value: str


class ParamUpdateRequest(BaseModel):
    param_value: str


@app.get("/api/products/{product_id}/params")
async def get_product_params(product_id: int):
    """获取产品的所有技术参数"""
    logger.info(f"[查询] 产品参数 | product_id={product_id}")
    conn = get_db()
    try:
        cursor = conn.cursor()
        sql = "SELECT * FROM part_params WHERE part_id = %s ORDER BY sort_order, id"
        logger.debug(f"[SQL] {sql} | params=({product_id},)")
        cursor.execute(sql, (product_id,))
        params = cursor.fetchall()
        logger.info(f"[查询] 产品参数完成 | product_id={product_id}, 共 {len(params)} 条参数")
        return params
    except Exception as e:
        logger.error(f"[查询] 产品参数失败 | product_id={product_id}, error={e}")
        raise
    finally:
        conn.close()


@app.post("/api/products/{product_id}/params")
async def create_product_param(product_id: int, req: ParamCreateRequest):
    """新增产品技术参数"""
    logger.info(f"[新增] 产品参数 | product_id={product_id}, value={req.param_value}")
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM parts WHERE id = %s", (product_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="产品不存在")

        cursor.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM part_params WHERE part_id = %s", (product_id,))
        next_order = cursor.fetchone()['next_order']

        sql = "INSERT INTO part_params (part_id, param_value, sort_order) VALUES (%s, %s, %s)"
        logger.debug(f"[SQL] {sql} | params=({product_id}, {req.param_value}, {next_order})")
        cursor.execute(sql, (product_id, req.param_value, next_order))
        cursor.execute("UPDATE parts SET update_time_2 = CURRENT_TIMESTAMP WHERE id = %s", (product_id,))
        conn.commit()
        param_id = cursor.lastrowid

        logger.info(f"[新增] 产品参数完成 | param_id={param_id}")
        return {"id": param_id, "part_id": product_id, "param_value": req.param_value, "sort_order": next_order}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[新增] 产品参数失败 | product_id={product_id}, error={e}")
        raise
    finally:
        conn.close()


@app.put("/api/products/{product_id}/params/{param_id}")
async def update_product_param(product_id: int, param_id: int, req: ParamUpdateRequest):
    """更新产品技术参数"""
    logger.info(f"[修改] 产品参数 | product_id={product_id}, param_id={param_id}, value={req.param_value}")
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM part_params WHERE id = %s AND part_id = %s", (param_id, product_id))
        old = cursor.fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="参数不存在")

        sql = "UPDATE part_params SET param_value = %s WHERE id = %s"
        logger.debug(f"[SQL] {sql} | params=({req.param_value}, {param_id})")
        cursor.execute(sql, (req.param_value, param_id))
        cursor.execute("UPDATE parts SET update_time_2 = CURRENT_TIMESTAMP WHERE id = %s", (product_id,))
        conn.commit()

        logger.info(f"[修改] 产品参数完成 | param_id={param_id}, old_value={old['param_value']}, new_value={req.param_value}")
        return {"message": "更新成功", "id": param_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[修改] 产品参数失败 | param_id={param_id}, error={e}")
        raise
    finally:
        conn.close()


@app.delete("/api/products/{product_id}/params/{param_id}")
async def delete_product_param(product_id: int, param_id: int):
    """删除产品技术参数"""
    logger.info(f"[删除] 产品参数 | product_id={product_id}, param_id={param_id}")
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM part_params WHERE id = %s AND part_id = %s", (param_id, product_id))
        old = cursor.fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="参数不存在")

        sql = "DELETE FROM part_params WHERE id = %s"
        logger.debug(f"[SQL] {sql} | params=({param_id},)")
        cursor.execute(sql, (param_id,))
        cursor.execute("UPDATE parts SET update_time_2 = CURRENT_TIMESTAMP WHERE id = %s", (product_id,))
        conn.commit()

        logger.info(f"[删除] 产品参数完成 | param_id={param_id}, value={old['param_value']}")
        return {"message": "删除成功", "id": param_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[删除] 产品参数失败 | param_id={param_id}, error={e}")
        raise
    finally:
        conn.close()

