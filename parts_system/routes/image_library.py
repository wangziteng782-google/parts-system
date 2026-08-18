from typing import Optional

from pydantic import BaseModel

from ..bootstrap import app, templates
from ..config import *
from ..model import *
from ..util import *

# ========== 图片库（parts_new）API ==========

@app.get("/api/image-library/categories")
async def image_library_categories():
    """获取 parts_new 表的分类列表（含数量），空值归为'其他'"""
    logger.info("[图片库] 查询分类列表")
    conn = get_db()
    try:
        cursor = conn.cursor()
        sql = """
            SELECT 
                CASE WHEN category IS NULL OR category = '' THEN '其他' ELSE category END AS cat_name,
                COUNT(*) AS cnt
            FROM parts_new
            WHERE product_images IS NOT NULL AND product_images != '[]' AND product_images != ''
            GROUP BY cat_name
            ORDER BY cnt DESC
        """
        cursor.execute(sql)
        rows = cursor.fetchall()
        result = [{"name": r['cat_name'], "count": r['cnt']} for r in rows]
        logger.info(f"[图片库] 分类列表完成 | 共 {len(result)} 个分类")
        return result
    except Exception as e:
        logger.error(f"[图片库] 查询分类失败 | error={e}")
        raise
    finally:
        conn.close()


@app.get("/api/image-library/products")
async def image_library_products(
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 30,
):
    """获取 parts_new 表中有图片的产品（分页），返回产品信息和图片列表"""
    logger.info(f"[图片库] 查询产品 | category={category}, keyword={keyword}, page={page}")
    conn = get_db()
    try:
        cursor = conn.cursor()
        where = " WHERE product_images IS NOT NULL AND product_images != '[]' AND product_images != ''"
        params = []

        if category:
            if category == '其他':
                where += " AND (category IS NULL OR category = '')"
            else:
                where += " AND category = %s"
                params.append(category)

        if keyword:
            where += " AND (product_name LIKE %s OR model LIKE %s)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        # 查总数
        count_sql = "SELECT COUNT(*) AS total FROM parts_new" + where
        cursor.execute(count_sql, params)
        total = cursor.fetchone()['total']

        # 查分页
        offset = (page - 1) * page_size
        sql = "SELECT id, product_name, product_brand, model, category, product_images FROM parts_new" + where
        sql += " ORDER BY id LIMIT %s OFFSET %s"
        params.extend([page_size, offset])
        cursor.execute(sql, params)
        items = cursor.fetchall()

        # 解析图片 JSON
        import json as _json
        for item in items:
            try:
                imgs = _json.loads(item['product_images']) if item['product_images'] else []
            except:
                imgs = [item['product_images']] if item['product_images'] else []
            item['images'] = imgs
            # 清理分类显示
            if not item['category']:
                item['category'] = '其他'

        logger.info(f"[图片库] 产品查询完成 | 返回 {len(items)} 条, 总计 {total}")
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        logger.error(f"[图片库] 查询产品失败 | error={e}")
        raise
    finally:
        conn.close()
