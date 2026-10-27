"""OA 系统外部接口（APIRouter，未挂主 app）

供 OA 系统反向调用：按产品名查型号列表、按产品 ID 查规格详情。
使用独立的 APIRouter，当前未在 bootstrap.py 中挂载到主 app（待启用）。
"""

from fastapi import APIRouter, HTTPException

from ..model import get_db

router = APIRouter(tags=["OA系统接口"])


@router.get("/api/oa/products")
async def oa_list_products(keyword: str = "", page: int = 1, page_size: int = 30):
    """按产品名称模糊查询，返回产品ID和型号列表（分页）。"""
    page = max(1, page)
    page_size = min(200, max(1, page_size))
    conn = get_db()
    try:
        cursor = conn.cursor()
        where = " WHERE status=1"
        params = []
        if keyword:
            where += " AND (product_name LIKE %s OR model LIKE %s)"
            pattern = f"%{keyword.strip()}%"
            params.extend([pattern, pattern])
        cursor.execute(f"SELECT COUNT(*) AS total FROM parts{where}", params)
        total = cursor.fetchone()["total"]
        offset = (page - 1) * page_size
        cursor.execute(
            f"""SELECT id, product_name, model, product_brand, product_type
                FROM parts{where}
                ORDER BY id DESC
                LIMIT %s OFFSET %s""",
            [*params, page_size, offset],
        )
        return {"items": cursor.fetchall(), "total": total, "page": page, "page_size": page_size}
    finally:
        conn.close()


@router.get("/api/oa/products/by-model")
async def oa_get_product_by_model(model: str):
    """按型号精确查询产品ID，供URL跳转定位使用。"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, product_name, model, product_brand, product_type
               FROM parts
               WHERE model=%s AND status=1
               ORDER BY update_time_2 DESC, id DESC
               LIMIT 1""",
            (model.strip(),),
        )
        product = cursor.fetchone()
        if not product:
            raise HTTPException(status_code=404, detail=f"未找到型号为 {model} 的产品")
        return product
    finally:
        conn.close()


@router.get("/api/oa/products/{product_id}/specs")
async def oa_get_specs(product_id: int):
    """按产品ID查询所有规格（规格字典）。"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, spec_name, spec_value, sort_order
               FROM product_variant_specs
               WHERE part_id=%s AND is_active=1
               ORDER BY sort_order, id""",
            (product_id,),
        )
        grouped = {}
        for row in cursor.fetchall():
            grouped.setdefault(row["spec_name"], []).append({
                "id": row["id"],
                "value": row["spec_value"],
            })
        return [{"spec_name": name, "values": values} for name, values in grouped.items()]
    finally:
        conn.close()


@router.get("/api/oa/products/{product_id}/combinations")
async def oa_get_combinations(product_id: int):
    """按产品ID查询所有规格组合（笛卡尔积）。"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT link.variant_group_id, spec.spec_name, spec.spec_value,
                      link.is_discontinued
               FROM product_variant_group_specs link
               JOIN product_variant_specs spec ON spec.id = link.spec_id
               WHERE link.part_id=%s AND spec.is_active=1
               ORDER BY link.variant_group_id, link.sort_order""",
            (product_id,),
        )
        groups = {}
        for row in cursor.fetchall():
            gid = row["variant_group_id"]
            if gid not in groups:
                groups[gid] = {
                    "variant_group_id": gid,
                    "specs": [],
                    "is_discontinued": False,
                }
            groups[gid]["specs"].append({
                "name": row["spec_name"],
                "value": row["spec_value"],
            })
            if row["is_discontinued"]:
                groups[gid]["is_discontinued"] = True
        return list(groups.values())
    finally:
        conn.close()
