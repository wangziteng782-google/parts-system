from fastapi import HTTPException

from ..bootstrap import app
from ..config import logger
from ..model import get_db


@app.get("/api/products/{product_id}/relations")
async def get_product_relations(product_id: int):
    """获取产品的关联产品列表。"""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT p.id, p.product_name, p.product_brand, p.model
               FROM product_relations r
               JOIN parts p ON r.related_product_id = p.id
               WHERE r.product_id = %s
               ORDER BY r.id""",
            (product_id,),
        )
        return {"relations": cur.fetchall()}
    finally:
        conn.close()


@app.post("/api/products/{product_id}/relations")
async def add_product_relation(product_id: int, req: dict):
    """添加关联产品（双向存储）。"""
    related_id = req.get("related_product_id")
    if not related_id:
        raise HTTPException(status_code=400, detail="缺少关联产品ID")
    if str(product_id) == str(related_id):
        raise HTTPException(status_code=400, detail="不能关联自身")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM parts WHERE id IN (%s, %s)", (product_id, related_id))
        if cur.rowcount < 2:
            raise HTTPException(status_code=404, detail="产品不存在")
        cur.execute(
            "SELECT id FROM product_relations WHERE product_id=%s AND related_product_id=%s",
            (product_id, related_id),
        )
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="已关联该产品")
        cur.execute(
            "INSERT INTO product_relations (product_id, related_product_id) VALUES (%s,%s),(%s,%s)",
            (product_id, related_id, related_id, product_id),
        )
        conn.commit()
        return {"message": "关联成功"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"[关联产品] 失败 | product_id={product_id}, related={related_id}, error={e}")
        raise HTTPException(status_code=500, detail="关联失败")
    finally:
        conn.close()


@app.delete("/api/products/{product_id}/relations/{related_id}")
async def delete_product_relation(product_id: int, related_id: int):
    """删除关联产品（双向删除）。"""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM product_relations WHERE (product_id=%s AND related_product_id=%s) OR (product_id=%s AND related_product_id=%s)",
            (product_id, related_id, related_id, product_id),
        )
        conn.commit()
        return {"message": "删除成功"}
    except Exception as e:
        conn.rollback()
        logger.error(f"[关联产品] 删除失败 | product_id={product_id}, related={related_id}, error={e}")
        raise HTTPException(status_code=500, detail="删除失败")
    finally:
        conn.close()
