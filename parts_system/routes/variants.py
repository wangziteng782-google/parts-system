import uuid
import time
from typing import Optional, List

from fastapi import HTTPException
from pydantic import BaseModel

from ..bootstrap import app, templates
from ..config import *
from ..model import *
from ..model import get_oa_db as _get_oa_db
from ..util import *
from ..audit import write_operation_log

_supplier_cache = None  # (fetched_at, [rows])
_SUPPLIER_CACHE_TTL = 60  # 秒，供应商列表变更频率低

# ========== 产品规格与供应商价格 ==========
class VariantSpecRequest(BaseModel):
    spec_name: str
    spec_value: str


class VariantSpecNameUpdateRequest(BaseModel):
    old_name: str
    new_name: str


class VariantPriceRequest(BaseModel):
    variant_group_id: str
    supplier: str = ""  # 后端从OA自动填充
    no_tax_price: Optional[float] = None
    purchase_special_invoice: Optional[float] = None
    purchase_general_invoice: Optional[float] = None
    purchase_shipping: Optional[float] = None
    freight_remark: Optional[str] = None
    retail_price: Optional[float] = None
    retail_ladder_price: Optional[float] = None
    retail_tax: Optional[float] = None
    retail_shipping: Optional[float] = None
    shipping_origin: Optional[str] = None
    shipping_time: Optional[str] = None
    warranty_time: Optional[str] = None
    daily_order_time: Optional[str] = None
    quote_time: Optional[str] = None
    expire_date: Optional[str] = None
    is_external_visible: bool = False
    oa_supplier_id: int  # 必填，从OA选择
    external_price_fields: Optional[str] = None
    remark: Optional[str] = None


class VariantSelection(BaseModel):
    spec_name: str
    spec_value: str


class VariantGroupRequest(BaseModel):
    specs: List[VariantSelection]


def _get_oa_supplier_name(oa_id: int) -> str:
    """从OA获取供应商名称，不存在则抛异常"""
    oa_conn = _get_oa_db()
    try:
        oa_cur = oa_conn.cursor()
        oa_cur.execute("SELECT supplier_name FROM yh_supplier WHERE id=%s AND delete_time IS NULL", (oa_id,))
        row = oa_cur.fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="OA供应商不存在")
        return row["supplier_name"]
    finally:
        oa_conn.close()


def _variant_spec_catalog(cur, product_id: int):
    """按规格名及规格值顺序读取规格字典。"""
    cur.execute(
        """SELECT id, spec_name, spec_value, sort_order
           FROM product_variant_specs
           WHERE part_id=%s AND is_active=1
           ORDER BY sort_order, id""",
        (product_id,),
    )
    catalog = {}
    for row in cur.fetchall():
        catalog.setdefault(row['spec_name'], []).append(row)
    return catalog


def _required_spec_rules(cur, product_id: int):
    """返回命中规则；分类或名称为空表示不限制对应条件。"""
    cur.execute(
        """SELECT rule.id, rule.spec_name, rule.is_required, rule.is_locked,
                  rule.sort_order, rule.remark,
                  rule.product_type AS rule_product_type,
                  rule.product_name AS rule_product_name,
                  rule.product_name_match_mode,
                  (
                    CASE WHEN TRIM(rule.product_type)='' THEN 0 ELSE 1 END
                    + CASE
                        WHEN TRIM(rule.product_name)='' THEN 0
                        WHEN rule.product_name_match_mode='exact' THEN 20
                        WHEN rule.product_name_match_mode='contains' THEN 10
                        ELSE 0
                      END
                  ) AS match_specificity
           FROM parts part
           JOIN product_spec_required_rules rule
             ON (
                TRIM(rule.product_type)=''
                OR TRIM(rule.product_type) COLLATE utf8mb4_unicode_ci
                   = TRIM(COALESCE(part.product_type,'')) COLLATE utf8mb4_unicode_ci
             )
            AND (
                TRIM(rule.product_name)=''
                OR (
                    rule.product_name_match_mode='exact'
                    AND TRIM(rule.product_name) COLLATE utf8mb4_unicode_ci
                        = TRIM(COALESCE(part.product_name,''))
                          COLLATE utf8mb4_unicode_ci
                )
                OR (
                    rule.product_name_match_mode='contains'
                    AND LOCATE(
                        TRIM(rule.product_name) COLLATE utf8mb4_unicode_ci,
                        TRIM(COALESCE(part.product_name,''))
                          COLLATE utf8mb4_unicode_ci
                    ) > 0
                )
            )
            AND NOT (TRIM(rule.product_type)='' AND TRIM(rule.product_name)='')
            AND rule.status=1
           WHERE part.id=%s
           ORDER BY
             match_specificity DESC,
             rule.sort_order, rule.id""",
        (product_id,),
    )
    # 同名规格同时命中多条规则时，条件更多的规则优先；
    # 返回前按显示顺序排列，避免前端出现重复规格名。
    deduplicated = {}
    for row in cur.fetchall():
        deduplicated.setdefault(row['spec_name'], row)
    return sorted(
        deduplicated.values(),
        key=lambda row: (row.get('sort_order', 0), row['id']),
    )


def _locked_required_spec_names(cur, product_id: int):
    return {
        row['spec_name']
        for row in _required_spec_rules(cur, product_id)
        if row.get('is_required') and row.get('is_locked')
    }


def _variant_group_links(cur, product_id: int):
    cur.execute(
        """SELECT link.id, link.variant_group_id, link.spec_id, link.sort_order,
                  spec.spec_name, spec.spec_value, spec.is_active
           FROM product_variant_group_specs link
           JOIN product_variant_specs spec ON spec.id=link.spec_id
           WHERE link.part_id=%s
           ORDER BY link.variant_group_id, link.sort_order, link.id""",
        (product_id,),
    )
    groups = {}
    for row in cur.fetchall():
        groups.setdefault(row['variant_group_id'], []).append(row)
    return groups


def _insert_variant_group(cur, product_id: int, spec_ids, group_id=None):
    group_id = group_id or uuid.uuid4().hex
    unique_ids = list(dict.fromkeys(spec_ids))
    cur.executemany(
        """INSERT INTO product_variant_group_specs
               (part_id, variant_group_id, spec_id, sort_order)
           VALUES(%s,%s,%s,%s)""",
        [(product_id, group_id, spec_id, index) for index, spec_id in enumerate(unique_ids)],
    )
    return group_id


def _initialize_variant_groups(cur, product_id: int):
    """首次把当前笛卡尔积持久化；旧报价组合优先沿用原ID并绑定缺少规格的第一个值。"""
    cur.execute(
        "SELECT variant_groups_initialized FROM parts WHERE id=%s FOR UPDATE",
        (product_id,),
    )
    part = cur.fetchone()
    if not part:
        raise HTTPException(status_code=404, detail="产品不存在")
    if part.get('variant_groups_initialized'):
        return

    catalog = _variant_spec_catalog(cur, product_id)
    if not catalog:
        cur.execute(
            "UPDATE parts SET variant_groups_initialized=1 WHERE id=%s",
            (product_id,),
        )
        return

    spec_names = list(catalog.keys())
    existing_groups = _variant_group_links(cur, product_id)

    # 已有价格组合缺少新规格维度时，给它补上每个规格名的第一个值，
    # 保留原 variant_group_id，因此原供应商与价格仍然有效。
    for group_id, links in existing_groups.items():
        linked_names = {link['spec_name'] for link in links}
        for order, spec_name in enumerate(spec_names):
            if spec_name not in linked_names:
                default_spec_id = catalog[spec_name][0]['id']
                cur.execute(
                    """INSERT IGNORE INTO product_variant_group_specs
                           (part_id,variant_group_id,spec_id,sort_order)
                       VALUES(%s,%s,%s,%s)""",
                    (product_id, group_id, default_spec_id, order),
                )

    existing_groups = _variant_group_links(cur, product_id)
    signatures = {
        tuple(sorted(link['spec_id'] for link in links)): group_id
        for group_id, links in existing_groups.items()
    }

    # 补齐当前尚不存在的组合；这些组合没有价格，前端显示为待配置。
    for selection in product(*[catalog[name] for name in spec_names]):
        spec_ids = [item['id'] for item in selection]
        signature = tuple(sorted(spec_ids))
        if signature not in signatures:
            group_id = _insert_variant_group(cur, product_id, spec_ids)
            signatures[signature] = group_id

    cur.execute(
        "UPDATE parts SET variant_groups_initialized=1 WHERE id=%s",
        (product_id,),
    )


def _expand_groups_for_new_spec_value(
    cur,
    product_id: int,
    spec_id: int,
    spec_name: str,
    is_new_name: bool,
):
    """新增规格值后增量扩展组合；新规格名第一个值沿用全部旧组合ID。"""
    groups = {
        group_id: links
        for group_id, links in _variant_group_links(cur, product_id).items()
        if all(link.get('is_active') for link in links)
    }
    if not groups:
        _insert_variant_group(cur, product_id, [spec_id])
        return

    if is_new_name:
        # 新规格名的第一个值直接追加到旧组合，报价通过原组合ID自动保留。
        for order, group_id in enumerate(groups):
            cur.execute(
                """INSERT IGNORE INTO product_variant_group_specs
                       (part_id,variant_group_id,spec_id,sort_order)
                   VALUES(%s,%s,%s,%s)""",
                (product_id, group_id, spec_id, len(groups[group_id])),
            )
        return

    # 同一规格名新增第二、第三个值：按“其他规格值”去重，
    # 每个基础组合生成一个新的待配置组合，不复制任何供应商价格。
    existing_signatures = {
        tuple(sorted(link['spec_id'] for link in links))
        for links in groups.values()
    }
    bases = {}
    for links in groups.values():
        other_ids = tuple(sorted(
            link['spec_id'] for link in links if link['spec_name'] != spec_name
        ))
        bases.setdefault(other_ids, list(other_ids))

    for other_ids in bases.values():
        new_ids = [*other_ids, spec_id]
        signature = tuple(sorted(new_ids))
        if signature not in existing_signatures:
            _insert_variant_group(cur, product_id, new_ids)
            existing_signatures.add(signature)


def _recalculate_part_display_price(product_id, cur):
    """多规格时把所有对外展示价的 min/max 写回 parts，单规格/无价格时写 NULL。"""
    cur.execute(
        """SELECT COUNT(DISTINCT variant_group_id) AS count
           FROM product_variant_prices WHERE part_id=%s""",
        (product_id,),
    )
    if cur.fetchone()['count'] <= 1:
        cur.execute(
            "UPDATE parts SET display_price_min=NULL, display_price_max=NULL WHERE id=%s",
            (product_id,),
        )
        return
    cur.execute(
        """SELECT no_tax_price, purchase_special_invoice, purchase_general_invoice,
                  external_price_fields
           FROM product_variant_prices WHERE part_id=%s""",
        (product_id,),
    )
    prices = []
    for row in cur.fetchall():
        fields = (row.get('external_price_fields') or '').split(',')
        if 'no_tax' in fields and row.get('no_tax_price') is not None:
            prices.append(float(row['no_tax_price']))
        if 'special' in fields and row.get('purchase_special_invoice') is not None:
            prices.append(float(row['purchase_special_invoice']))
        if 'general' in fields and row.get('purchase_general_invoice') is not None:
            prices.append(float(row['purchase_general_invoice']))
    if prices:
        cur.execute(
            "UPDATE parts SET display_price_min=%s, display_price_max=%s WHERE id=%s",
            (min(prices), max(prices), product_id),
        )
    else:
        cur.execute(
            "UPDATE parts SET display_price_min=NULL, display_price_max=NULL WHERE id=%s",
            (product_id,),
        )


@app.get("/api/products/{product_id}/variant-specs")
async def get_variant_specs(product_id: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM product_variant_specs
               WHERE part_id=%s AND is_active=1
               ORDER BY sort_order,id""",
            (product_id,),
        )
        rows = cur.fetchall()
        grouped = {}
        for row in rows:
            item = grouped.setdefault(row['spec_name'], {'spec_name': row['spec_name'], 'values': []})
            item['values'].append({'id': row['id'], 'value': row['spec_value']})

        # 规则规格名可以在没有规格值时直接展示，但不写空值到规格表，
        # 因此不会参与笛卡尔积，也不会生成“规格值为空”的组合。
        result = []
        for rule in _required_spec_rules(cur, product_id):
            item = grouped.pop(
                rule['spec_name'],
                {'spec_name': rule['spec_name'], 'values': []},
            )
            item.update({
                'is_required': bool(rule.get('is_required')),
                'is_locked': bool(rule.get('is_locked')),
                'source': 'required_rule',
                'rule_id': rule['id'],
                'pending': not item['values'],
            })
            result.append(item)
        for item in grouped.values():
            item.update({
                'is_required': False,
                'is_locked': False,
                'source': 'product',
                'rule_id': None,
                'pending': False,
            })
            result.append(item)
        return result
    finally:
        conn.close()


@app.post("/api/products/{product_id}/variant-specs")
async def add_variant_spec(product_id: int, req: VariantSpecRequest):
    name, value = req.spec_name.strip(), req.spec_value.strip()
    if not name or not value:
        raise HTTPException(status_code=400, detail="规格名和规格值不能为空")
    conn = get_db()
    try:
        cur = conn.cursor()
        ensure_employee_operation_logs_table(conn)
        cur.execute("SELECT id FROM parts WHERE id=%s FOR UPDATE", (product_id,))
        if not cur.fetchone(): raise HTTPException(status_code=404, detail="产品不存在")
        _initialize_variant_groups(cur, product_id)
        cur.execute(
            """SELECT COUNT(*) AS count FROM product_variant_specs
               WHERE part_id=%s AND spec_name=%s AND is_active=1""",
            (product_id, name),
        )
        is_new_name = cur.fetchone()['count'] == 0
        cur.execute(
            """SELECT id,is_active FROM product_variant_specs
               WHERE part_id=%s AND spec_name=%s AND spec_value=%s""",
            (product_id, name, value),
        )
        existing_spec = cur.fetchone()
        if existing_spec and existing_spec['is_active']:
            raise HTTPException(status_code=409, detail="该规格值已存在")
        if existing_spec:
            spec_id = existing_spec['id']
            cur.execute(
                """UPDATE product_variant_specs SET is_active=1
                   WHERE id=%s AND part_id=%s""",
                (spec_id, product_id),
            )
            catalog = _variant_spec_catalog(cur, product_id)
            active_names = list(catalog.keys())
            groups = _variant_group_links(cur, product_id)
            restored_group_count = 0
            for group_id, links in groups.items():
                if not any(link['spec_id'] == spec_id for link in links):
                    continue
                linked_names = {link['spec_name'] for link in links}
                for order, active_name in enumerate(active_names):
                    if active_name not in linked_names:
                        cur.execute(
                            """INSERT IGNORE INTO product_variant_group_specs
                                   (part_id,variant_group_id,spec_id,sort_order)
                               VALUES(%s,%s,%s,%s)""",
                            (product_id, group_id, catalog[active_name][0]['id'], order),
                        )
                restored_group_count += 1
            if restored_group_count == 0:
                _expand_groups_for_new_spec_value(
                    cur, product_id, spec_id, name, is_new_name
                )
            cur.execute(
                "UPDATE parts SET update_time_2=CURRENT_TIMESTAMP WHERE id=%s",
                (product_id,),
            )
            write_operation_log(
                cur,
                part_id=product_id,
                operation_type="UPDATE",
                module_code="SPEC",
                detail=f"恢复规格：{name}={value}",
            )
            conn.commit()
            return {
                'id': spec_id,
                'spec_name': name,
                'spec_value': value,
                'restored': True,
                'restored_groups': restored_group_count,
            }
        cur.execute(
            "SELECT COALESCE(MAX(sort_order),-1)+1 AS next_order FROM product_variant_specs WHERE part_id=%s AND spec_name=%s",
            (product_id, name),
        )
        next_order = cur.fetchone()['next_order']
        cur.execute(
            """INSERT INTO product_variant_specs(part_id,spec_name,spec_value,sort_order)
               VALUES(%s,%s,%s,%s)""",
            (product_id, name, value, next_order),
        )
        spec_id = cur.lastrowid
        _expand_groups_for_new_spec_value(
            cur, product_id, spec_id, name, is_new_name
        )
        write_operation_log(
            cur,
            part_id=product_id,
            operation_type="CREATE",
            module_code="SPEC",
            detail=f"新增规格：{name}={value}",
        )
        cur.execute("UPDATE parts SET update_time_2=CURRENT_TIMESTAMP WHERE id=%s", (product_id,))
        conn.commit()
        return {
            'id': spec_id,
            'spec_name': name,
            'spec_value': value,
            'inherited_existing_prices': is_new_name,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.put("/api/products/{product_id}/variant-specs/{spec_id}")
async def update_variant_spec(product_id: int, spec_id: int, req: VariantSpecRequest):
    """原位修改规格值，保留规格ID以及现有规格组合、供应商价格的关联关系。"""
    name, value = req.spec_name.strip(), req.spec_value.strip()
    if not name or not value:
        raise HTTPException(status_code=400, detail="规格名和规格值不能为空")
    conn = get_db()
    try:
        cur = conn.cursor()
        ensure_employee_operation_logs_table(conn)
        cur.execute(
            """SELECT id, spec_name, spec_value FROM product_variant_specs
               WHERE id=%s AND part_id=%s""",
            (spec_id, product_id),
        )
        current_spec = cur.fetchone()
        if not current_spec:
            raise HTTPException(status_code=404, detail="规格值不存在")
        locked_names = _locked_required_spec_names(cur, product_id)
        if current_spec['spec_name'] in locked_names and name != current_spec['spec_name']:
            raise HTTPException(
                status_code=409,
                detail=f"“{current_spec['spec_name']}”是该产品的固定规格名称，不能修改",
            )
        if name in locked_names and name != current_spec['spec_name']:
            raise HTTPException(
                status_code=409,
                detail=f"“{name}”已由必备规格规则配置，不能将其他规格改为该名称",
            )
        cur.execute(
            """SELECT id FROM product_variant_specs
               WHERE part_id=%s AND spec_name=%s AND spec_value=%s AND id<>%s""",
            (product_id, name, value, spec_id),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="该规格值已存在")
        cur.execute(
            """UPDATE product_variant_specs
               SET spec_name=%s, spec_value=%s
               WHERE id=%s AND part_id=%s""",
            (name, value, spec_id, product_id),
        )
        write_operation_log(
            cur,
            part_id=product_id,
            operation_type="UPDATE",
            module_code="SPEC",
            detail=(
                f"修改规格：{current_spec['spec_name']}={current_spec['spec_value']} "
                f"→ {name}={value}"
            ),
        )
        cur.execute("UPDATE parts SET update_time_2=CURRENT_TIMESTAMP WHERE id=%s", (product_id,))
        conn.commit()
        return {'id': spec_id, 'spec_name': name, 'spec_value': value, 'message': '规格值已修改'}
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.put("/api/products/{product_id}/variant-spec-name")
async def update_variant_spec_name(product_id: int, req: VariantSpecNameUpdateRequest):
    """原位批量修改规格名，保留规格ID、规格组合以及供应商价格关联。"""
    old_name = req.old_name.strip()
    new_name = req.new_name.strip()
    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="规格名称不能为空")
    if len(new_name) > 100:
        raise HTTPException(status_code=400, detail="规格名称不能超过100个字符")
    if old_name == new_name:
        return {'message': '规格名称未变化', 'updated_count': 0}

    conn = get_db()
    try:
        cur = conn.cursor()
        ensure_employee_operation_logs_table(conn)
        locked_names = _locked_required_spec_names(cur, product_id)
        if old_name in locked_names:
            raise HTTPException(
                status_code=409,
                detail=f"“{old_name}”是该产品的固定规格名称，不能修改",
            )
        if new_name in locked_names:
            raise HTTPException(
                status_code=409,
                detail=f"“{new_name}”已由必备规格规则配置，不能将其他规格改为该名称",
            )
        cur.execute(
            """SELECT id FROM product_variant_specs
               WHERE part_id=%s AND spec_name=%s FOR UPDATE""",
            (product_id, old_name),
        )
        rows = cur.fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="原规格名称不存在")
        cur.execute(
            "SELECT id FROM product_variant_specs WHERE part_id=%s AND spec_name=%s LIMIT 1",
            (product_id, new_name),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="新的规格名称已经存在，请使用其他名称")

        cur.execute(
            "UPDATE product_variant_specs SET spec_name=%s WHERE part_id=%s AND spec_name=%s",
            (new_name, product_id, old_name),
        )
        updated_count = cur.rowcount
        write_operation_log(
            cur,
            part_id=product_id,
            operation_type="UPDATE",
            module_code="SPEC",
            detail=f"修改规格名称：{old_name} → {new_name}；影响规格值数量：{updated_count}",
        )
        cur.execute("UPDATE parts SET update_time_2=CURRENT_TIMESTAMP WHERE id=%s", (product_id,))
        conn.commit()
        logger.info(
            f"[规格名修改] 完成 | product_id={product_id}, old={old_name}, "
            f"new={new_name}, count={updated_count}"
        )
        return {
            'message': '规格名称已修改',
            'old_name': old_name,
            'new_name': new_name,
            'updated_count': updated_count,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(
            f"[规格名修改] 失败 | product_id={product_id}, old={old_name}, "
            f"new={new_name}, error={e}"
        )
        raise
    finally:
        conn.close()


@app.get("/api/products/{product_id}/variant-prices")
async def get_variant_prices(product_id: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM product_variant_prices WHERE part_id=%s ORDER BY id", (product_id,))
        prices = cur.fetchall()
        cur.execute(
            """SELECT link.variant_group_id, spec.spec_name, spec.spec_value
               FROM product_variant_group_specs link
               JOIN product_variant_specs spec ON spec.id = link.spec_id
               WHERE link.part_id=%s
               ORDER BY link.sort_order,link.id""",
            (product_id,)
        )
        specs = {}
        for row in cur.fetchall():
            specs.setdefault(row['variant_group_id'], []).append({'name': row['spec_name'], 'value': row['spec_value']})
        for row in prices: row['specs'] = specs.get(row['variant_group_id'], [])
        return prices
    finally:
        conn.close()


@app.get("/api/products/{product_id}/variant-combinations")
async def get_variant_combinations(product_id: int):
    """返回已持久化组合；首次调用补齐当前笛卡尔积，之后只做增量维护。"""
    conn = get_db()
    try:
        cur = conn.cursor()
        _initialize_variant_groups(cur, product_id)
        conn.commit()
        groups = _variant_group_links(cur, product_id)
        cur.execute(
            """SELECT * FROM product_variant_prices
               WHERE part_id=%s ORDER BY variant_group_id,id""",
            (product_id,),
        )
        prices_by_group = {}
        for row in cur.fetchall():
            prices_by_group.setdefault(row['variant_group_id'], []).append(row)

        combinations = []
        for group_id, links in groups.items():
            prices = prices_by_group.get(group_id, [])
            combinations.append({
                'variant_group_id': group_id,
                'specs': [
                    {
                        'id': link['spec_id'],
                        'name': link['spec_name'],
                        'value': link['spec_value'],
                        'is_active': bool(link['is_active']),
                    }
                    for link in links
                ],
                'prices': prices,
                'is_configured': bool(prices),
                'is_active': all(bool(link['is_active']) for link in links),
                '_first_link_id': min(link.get('id', 0) or 0 for link in links),
            })
        combinations.sort(
            key=lambda item: (
                0 if item['is_configured'] else 1,
                item['_first_link_id'],
                item['variant_group_id'],
            )
        )
        for item in combinations:
            item.pop('_first_link_id', None)
        return combinations
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.post("/api/products/{product_id}/variant-groups")
async def resolve_variant_group(product_id: int, req: VariantGroupRequest):
    selected = sorted({(s.spec_name.strip(), s.spec_value.strip()) for s in req.specs if s.spec_name.strip() and s.spec_value.strip()})
    if not selected:
        raise HTTPException(status_code=400, detail="请至少选择一个规格")
    conn = get_db()
    try:
        cur = conn.cursor()
        ensure_employee_operation_logs_table(conn)
        selected_ids = []
        for name, value in selected:
            cur.execute(
                "SELECT id FROM product_variant_specs WHERE part_id=%s AND spec_name=%s AND spec_value=%s",
                (product_id, name, value)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=400, detail=f"规格值不存在: {name}={value}")
            selected_ids.append(row['id'])
        cur.execute(
            "SELECT variant_group_id,spec_id FROM product_variant_group_specs WHERE part_id=%s ORDER BY variant_group_id,spec_id",
            (product_id,)
        )
        groups = {}
        for row in cur.fetchall():
            groups.setdefault(row['variant_group_id'], []).append(row['spec_id'])
        for group_id, spec_ids in groups.items():
            if sorted(spec_ids) == sorted(selected_ids):
                return {'variant_group_id': group_id}
        group_id = __import__('uuid').uuid4().hex
        cur.executemany(
            "INSERT INTO product_variant_group_specs(part_id,variant_group_id,spec_id,sort_order) VALUES(%s,%s,%s,%s)",
            [(product_id, group_id, spec_id, i) for i, spec_id in enumerate(selected_ids)]
        )
        write_operation_log(
            cur,
            part_id=product_id,
            operation_type="CREATE",
            module_code="SPEC",
            detail=(
                "新增规格组合："
                + "、".join(f"{name}={value}" for name, value in selected)
            ),
        )
        conn.commit()
        return {'variant_group_id': group_id}
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.delete("/api/products/{product_id}/variant-groups/{group_id}")
async def delete_variant_group(product_id: int, group_id: str):
    """直接删除一个规格组合及其全部供应商价格；后续只基于剩余组合增量扩展。"""
    group_id = group_id.strip()
    if not group_id:
        raise HTTPException(status_code=400, detail="规格组合ID不能为空")
    conn = get_db()
    try:
        cur = conn.cursor()
        ensure_employee_operation_logs_table(conn)
        cur.execute(
            """SELECT COUNT(*) AS count FROM product_variant_group_specs
               WHERE part_id=%s AND variant_group_id=%s""",
            (product_id, group_id),
        )
        if cur.fetchone()['count'] == 0:
            raise HTTPException(status_code=404, detail="规格组合不存在")
        cur.execute(
            """DELETE FROM product_variant_prices
               WHERE part_id=%s AND variant_group_id=%s""",
            (product_id, group_id),
        )
        deleted_prices = cur.rowcount
        cur.execute(
            """DELETE FROM product_variant_group_specs
               WHERE part_id=%s AND variant_group_id=%s""",
            (product_id, group_id),
        )
        write_operation_log(
            cur,
            part_id=product_id,
            operation_type="DELETE",
            module_code="SPEC",
            detail=f"删除规格组合：{group_id}；同时删除供应商价格数量：{deleted_prices}",
        )
        cur.execute(
            "UPDATE parts SET update_time_2=CURRENT_TIMESTAMP WHERE id=%s",
            (product_id,),
        )
        conn.commit()
        return {
            'message': '规格组合已删除',
            'deleted_prices': deleted_prices,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.post("/api/products/{product_id}/variant-prices")
async def save_variant_price(product_id: int, req: VariantPriceRequest):
    if not req.variant_group_id.strip():
        raise HTTPException(status_code=400, detail="规格组合不能为空")
    if not req.oa_supplier_id:
        raise HTTPException(status_code=400, detail="请选择OA供应商")
    req.supplier = _get_oa_supplier_name(req.oa_supplier_id)
    fields = ['supplier','no_tax_price','purchase_special_invoice','purchase_general_invoice','purchase_shipping','freight_remark','retail_price','retail_ladder_price','retail_tax','retail_shipping','shipping_origin','shipping_time','warranty_time','daily_order_time','quote_time','expire_date','is_external_visible','oa_supplier_id','external_price_fields','remark']
    values = [getattr(req, f) for f in fields]
    conn = get_db()
    try:
        cur = conn.cursor()
        ensure_employee_operation_logs_table(conn)
        cur.execute("SELECT id FROM parts WHERE id=%s", (product_id,))
        if not cur.fetchone(): raise HTTPException(status_code=404, detail="产品不存在")
        cur.execute(
            "SELECT COUNT(*) AS count FROM product_variant_group_specs WHERE part_id=%s AND variant_group_id=%s",
            (product_id, req.variant_group_id)
        )
        if cur.fetchone()['count'] == 0:
            raise HTTPException(status_code=400, detail="规格组合不存在")
        cur.execute(
            "SELECT id FROM product_variant_prices WHERE part_id=%s AND variant_group_id=%s AND supplier=%s",
            (product_id, req.variant_group_id, req.supplier),
        )
        existed = cur.fetchone()
        cols = ','.join(fields); marks = ','.join(['%s'] * len(fields))
        updates = ','.join(f"{f}=VALUES({f})" for f in fields[1:])
        sql = f"INSERT INTO product_variant_prices(part_id,variant_group_id,{cols}) VALUES(%s,%s,{marks}) ON DUPLICATE KEY UPDATE {updates}"
        cur.execute(sql, [product_id, req.variant_group_id, *values])
        price_id = cur.lastrowid
        if not price_id:
            cur.execute(
                "SELECT id FROM product_variant_prices WHERE part_id=%s AND variant_group_id=%s AND supplier=%s",
                (product_id, req.variant_group_id, req.supplier)
            )
            price_id = cur.fetchone()['id']
        if req.is_external_visible:
            cur.execute(
                """UPDATE product_variant_prices
                   SET is_external_visible=0
                   WHERE part_id=%s AND variant_group_id=%s
                     AND id<>%s AND is_external_visible<>0""",
                (product_id, req.variant_group_id, price_id),
            )
        write_operation_log(
            cur,
            part_id=product_id,
            operation_type='UPDATE' if existed else 'CREATE',
            module_code='PRICE',
            detail=(
                f"{'修改' if existed else '新增'}供应商价格；规格组合：{req.variant_group_id}；"
                f"供应商：{req.supplier}；"
                f"对外展示：{'是' if req.is_external_visible else '否'}"
            ),
        )
        cur.execute("UPDATE parts SET update_time_2=CURRENT_TIMESTAMP WHERE id=%s", (product_id,))
        _recalculate_part_display_price(product_id, cur)
        conn.commit()
        cur.execute("SELECT update_time_2 FROM parts WHERE id=%s", (product_id,))
        updated_at = cur.fetchone()['update_time_2']
        return {'id': price_id, 'message': '规格组合价格已保存', 'update_time_2': updated_at}
    finally:
        conn.close()


@app.delete("/api/products/{product_id}/variant-specs/{spec_id}")
async def delete_variant_spec(product_id: int, spec_id: int):
    """停用规格值；保留所有历史组合、组合ID及供应商报价。"""
    conn = get_db()
    try:
        cur = conn.cursor()
        ensure_employee_operation_logs_table(conn)
        cur.execute(
            """SELECT id, spec_name, spec_value, is_active
               FROM product_variant_specs
               WHERE id=%s AND part_id=%s FOR UPDATE""",
            (spec_id, product_id),
        )
        spec = cur.fetchone()
        if not spec:
            raise HTTPException(status_code=404, detail="规格值不存在")
        if not spec.get('is_active', 1):
            raise HTTPException(status_code=409, detail="该规格值已经删除")

        cur.execute(
            """SELECT COUNT(DISTINCT links.variant_group_id) AS group_count,
                      COUNT(DISTINCT prices.id) AS price_count
               FROM product_variant_group_specs links
               LEFT JOIN product_variant_prices prices
                 ON prices.part_id=links.part_id
                AND prices.variant_group_id=links.variant_group_id
               WHERE links.part_id=%s AND links.spec_id=%s""",
            (product_id, spec_id),
        )
        preserved = cur.fetchone()
        cur.execute(
            """UPDATE product_variant_specs
               SET is_active=0
               WHERE id=%s AND part_id=%s""",
            (spec_id, product_id),
        )
        write_operation_log(
            cur,
            part_id=product_id,
            operation_type="DELETE",
            module_code="SPEC",
            detail=f"删除规格：{spec['spec_name']}={spec['spec_value']}（历史组合和价格保留）",
        )
        cur.execute("UPDATE parts SET update_time_2=CURRENT_TIMESTAMP WHERE id=%s", (product_id,))
        conn.commit()
        logger.info(
            f"[规格值停用] 完成 | product_id={product_id}, spec_id={spec_id}, "
            f"name={spec['spec_name']}, value={spec['spec_value']}, "
            f"preserved_groups={preserved['group_count']}, "
            f"preserved_prices={preserved['price_count']}"
        )
        return {
            'message': '规格值已从配置中删除，历史组合和供应商报价已保留',
            'preserved_groups': preserved['group_count'],
            'preserved_prices': preserved['price_count'],
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.delete("/api/products/{product_id}/variant-prices/{price_id}")
async def delete_variant_price(product_id: int, price_id: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        ensure_employee_operation_logs_table(conn)
        cur.execute("SELECT variant_group_id, supplier FROM product_variant_prices WHERE id=%s AND part_id=%s", (price_id, product_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="价格记录不存在")
        cur.execute("DELETE FROM product_variant_prices WHERE id=%s AND part_id=%s", (price_id, product_id))
        write_operation_log(
            cur,
            part_id=product_id,
            operation_type='DELETE',
            module_code='PRICE',
            detail=f"删除供应商价格；规格组合：{row['variant_group_id']}；供应商：{row['supplier']}",
        )
        cur.execute("UPDATE parts SET update_time_2=CURRENT_TIMESTAMP WHERE id=%s", (product_id,))
        _recalculate_part_display_price(product_id, cur)
        conn.commit()
        return {'message': '已删除'}
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()


class VariantPriceUpdateRequest(BaseModel):
    supplier: str = ""  # 后端从OA自动填充
    no_tax_price: Optional[float] = None
    purchase_special_invoice: Optional[float] = None
    purchase_general_invoice: Optional[float] = None
    purchase_shipping: Optional[float] = None
    freight_remark: Optional[str] = None
    retail_price: Optional[float] = None
    retail_ladder_price: Optional[float] = None
    retail_tax: Optional[float] = None
    retail_shipping: Optional[float] = None
    shipping_origin: Optional[str] = None
    shipping_time: Optional[str] = None
    warranty_time: Optional[str] = None
    daily_order_time: Optional[str] = None
    quote_time: Optional[str] = None
    expire_date: Optional[str] = None
    is_external_visible: bool = False
    oa_supplier_id: int  # 必填，从OA选择
    external_price_fields: Optional[str] = None
    remark: Optional[str] = None


class VariantExternalVisibilityRequest(BaseModel):
    is_external_visible: bool


@app.patch("/api/products/{product_id}/variant-prices/{price_id}/external-visible")
async def update_variant_external_visibility(
    product_id: int,
    price_id: int,
    req: VariantExternalVisibilityRequest,
):
    """单独切换供应商报价是否用于销售端展示。"""
    conn = get_db()
    try:
        cur = conn.cursor()
        ensure_employee_operation_logs_table(conn)
        cur.execute(
            """SELECT id, variant_group_id, supplier
               FROM product_variant_prices
               WHERE id=%s AND part_id=%s FOR UPDATE""",
            (price_id, product_id),
        )
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="供应商报价不存在")
        cur.execute(
            "UPDATE product_variant_prices SET is_external_visible=%s WHERE id=%s AND part_id=%s",
            (1 if req.is_external_visible else 0, price_id, product_id),
        )
        if req.is_external_visible:
            cur.execute(
                """UPDATE product_variant_prices
                   SET is_external_visible=0
                   WHERE part_id=%s AND variant_group_id=%s
                     AND id<>%s AND is_external_visible<>0""",
                (product_id, existing["variant_group_id"], price_id),
            )
        write_operation_log(
            cur,
            part_id=product_id,
            operation_type="UPDATE",
            module_code="PRICE",
            detail=(
                f"修改供应商报价对外展示；规格组合：{existing['variant_group_id']}；"
                f"供应商：{existing['supplier']}；"
                f"对外展示：{'是' if req.is_external_visible else '否'}"
            ),
        )
        cur.execute(
            "UPDATE parts SET update_time_2=CURRENT_TIMESTAMP WHERE id=%s",
            (product_id,),
        )
        conn.commit()
        return {
            "message": "已设为对外展示" if req.is_external_visible else "已取消对外展示",
            "is_external_visible": req.is_external_visible,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.put("/api/products/{product_id}/variant-prices/{price_id}")
async def update_variant_price(product_id: int, price_id: int, req: VariantPriceUpdateRequest):
    if not req.oa_supplier_id:
        raise HTTPException(status_code=400, detail="请选择OA供应商")
    # 从OA获取供应商名称
    oa_conn = _get_oa_db()
    try:
        oa_cur = oa_conn.cursor()
        oa_cur.execute("SELECT supplier_name FROM yh_supplier WHERE id=%s AND delete_time IS NULL", (req.oa_supplier_id,))
        oa_row = oa_cur.fetchone()
        if not oa_row:
            raise HTTPException(status_code=400, detail="OA供应商不存在")
        req.supplier = oa_row["supplier_name"]
    finally:
        oa_conn.close()
    fields = ['supplier','no_tax_price','purchase_special_invoice','purchase_general_invoice','purchase_shipping','freight_remark','retail_price','retail_ladder_price','retail_tax','retail_shipping','shipping_origin','shipping_time','warranty_time','daily_order_time','quote_time','expire_date','is_external_visible','oa_supplier_id','external_price_fields','remark']
    values = [getattr(req, f) for f in fields]
    conn = get_db()
    try:
        cur = conn.cursor()
        ensure_employee_operation_logs_table(conn)
        cur.execute("SELECT id, variant_group_id, supplier AS old_supplier FROM product_variant_prices WHERE id=%s AND part_id=%s", (price_id, product_id))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="价格记录不存在")
        set_clause = ','.join(f"{f}=%s" for f in fields)
        cur.execute(f"UPDATE product_variant_prices SET {set_clause} WHERE id=%s AND part_id=%s", [*values, price_id, product_id])
        if req.is_external_visible:
            cur.execute(
                """UPDATE product_variant_prices
                   SET is_external_visible=0
                   WHERE part_id=%s AND variant_group_id=%s
                     AND id<>%s AND is_external_visible<>0""",
                (product_id, existing['variant_group_id'], price_id),
            )
        write_operation_log(
            cur,
            part_id=product_id,
            operation_type='UPDATE',
            module_code='PRICE',
            detail=(
                f"修改供应商价格；规格组合：{existing['variant_group_id']}；"
                f"供应商：{existing['old_supplier']} → {req.supplier}；"
                f"对外展示：{'是' if req.is_external_visible else '否'}"
            ),
        )
        cur.execute("UPDATE parts SET update_time_2=CURRENT_TIMESTAMP WHERE id=%s", (product_id,))
        _recalculate_part_display_price(product_id, cur)
        conn.commit()
        return {'message': '已更新'}
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()


# ========== OA 供应商查询 ==========
@app.get("/api/oa/suppliers")
async def list_oa_suppliers(keyword: str = ""):
    """返回OA供应商列表，供前端下拉选择。支持keyword模糊搜索。"""
    global _supplier_cache
    now = time.time()

    if _supplier_cache and now - _supplier_cache[0] < _SUPPLIER_CACHE_TTL:
        rows = _supplier_cache[1]
    else:
        conn = _get_oa_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT id, supplier_name
                   FROM yh_supplier
                   WHERE delete_time IS NULL
                   ORDER BY id""",
            )
            rows = [
                {"oa_supplier_id": row["id"], "supplier_name": row["supplier_name"]}
                for row in cur.fetchall()
            ]
        finally:
            conn.close()
        _supplier_cache = (now, rows)

    if keyword:
        kw = keyword.lower()
        return [r for r in rows if kw in r["supplier_name"].lower()][:50]
    return rows


@app.get("/api/oa/suppliers/{supplier_id}")
async def get_oa_supplier(supplier_id: int):
    """返回OA供应商详情：名称+开票能力+税点。从 yh_supplier_detail 聚合。"""
    conn = _get_oa_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT s.id as oa_supplier_id, s.supplier_name,
                      MAX(d.is_special_invoice) as is_special_invoice,
                      MAX(d.is_normal_invoice) as is_normal_invoice,
                      MAX(d.is_no_invoice) as is_no_invoice,
                      GROUP_CONCAT(DISTINCT CASE WHEN d.special_tax_point > '' THEN d.special_tax_point END) as special_tax_point,
                      GROUP_CONCAT(DISTINCT CASE WHEN d.normal_tax_point > '' THEN d.normal_tax_point END) as normal_tax_point,
                      GROUP_CONCAT(DISTINCT CASE WHEN d.no_tax_point > '' THEN d.no_tax_point END) as no_tax_point
               FROM yh_supplier s
               LEFT JOIN yh_supplier_detail d ON s.id = d.supplier_id AND d.delete_time IS NULL
               WHERE s.id=%s AND s.delete_time IS NULL
               GROUP BY s.id, s.supplier_name""",
            (supplier_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="供应商不存在")
        return {
            "oa_supplier_id": row["oa_supplier_id"],
            "supplier_name": row["supplier_name"],
            "is_special_invoice": bool(row["is_special_invoice"]),
            "is_normal_invoice": bool(row["is_normal_invoice"]),
            "is_no_invoice": bool(row["is_no_invoice"]),
            "special_tax_point": row["special_tax_point"],
            "normal_tax_point": row["normal_tax_point"],
            "no_tax_point": row["no_tax_point"],
        }
    finally:
        conn.close()
