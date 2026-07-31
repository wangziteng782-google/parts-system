#!/usr/bin/env python
"""按照方案B把已导入的parts SPU整理为SKU、规格值、销售价和供应商报价。

默认只预览，不修改数据库：
    python jobs/migrate_parts_to_sku.py

正式执行：
    python jobs/migrate_parts_to_sku.py --execute

小批量执行：
    python jobs/migrate_parts_to_sku.py --execute --limit 3

安全约束：
- 只消费 prepare_sku_migration.py 生成并通过指纹校验的预检文件。
- 不删除、合并或软删除现有SPU。
- 不创建SKU扩展表。
- SKU编码确定且可反查，重复执行会更新原记录，不重复新增。
- 无法安全转换为decimal的价格不猜测，写0并关闭对应价格状态。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pymysql

from migrate_parts_to_spu import (
    DEFAULT_SOURCE_SQL_PATH,
    acquire_migration_lock,
    actor_name,
    clean_text,
    detail_html,
    limit_text,
    load_admin_ids,
    ordinary_images,
    parse_datetime,
    preserve_text,
    release_migration_lock,
    resolve_admin_id,
    source_file_sha256,
    source_rows_from_sql,
    source_times,
    target_db_config,
    write_json_atomic,
)
from prepare_sku_migration import (
    DEFAULT_JSON_PATH,
    decimal_value,
    normalized_text,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = PROJECT_DIR / "jobs" / "sku_migration_state.json"
DEFAULT_ERROR_PATH = PROJECT_DIR / "jobs" / "sku_migration_errors.jsonl"
DEFAULT_LOCK_PATH = PROJECT_DIR / "jobs" / "sku_migration.lock"
DATA_SOURCE = "parts.sql导入"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="迁移parts方案B SKU数据")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sku-group-id", action="append", dest="sku_group_ids")
    parser.add_argument("--source-sql", type=Path, default=DEFAULT_SOURCE_SQL_PATH)
    parser.add_argument("--preview", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--error-file", type=Path, default=DEFAULT_ERROR_PATH)
    parser.add_argument(
        "--sku-status",
        type=int,
        choices=(0, 1),
        default=1,
        help="默认1上架；如需下架导入可显式传入 --sku-status 0",
    )
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


def append_error(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")


def load_preview(path: Path, source_path: Path, source_hash: str) -> dict[str, Any]:
    preview = json.loads(path.read_text(encoding="utf-8"))
    if preview.get("version") != 1:
        raise RuntimeError("SKU预检文件版本不受支持，请重新生成")
    if preview.get("source_sha256") != source_hash:
        raise RuntimeError("SKU预检文件与当前parts.sql指纹不一致，请重新生成")
    if Path(preview.get("source_sql", "")).resolve() != source_path.resolve():
        raise RuntimeError("SKU预检文件不属于当前parts.sql")
    if preview.get("summary", {}).get("source_coverage") != preview.get(
        "summary", {}
    ).get("source_parts"):
        raise RuntimeError("SKU预检没有覆盖全部parts来源")
    return preview


def preview_fingerprint(preview: dict[str, Any]) -> str:
    stable = [
        (
            item["sku_group_id"],
            item["sku_code"],
            item["canonical_spu_id"],
            item["representative_parts_id"],
            item["nature"],
            item["retail_price"],
            item["source_parts_ids"],
        )
        for item in preview["skus"]
    ]
    raw = json.dumps(stable, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_state(
    path: Path, source_hash: str, preview_hash: str
) -> dict[str, Any]:
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if (
            state.get("version") != 1
            or state.get("source_sha256") != source_hash
            or state.get("preview_sha256") != preview_hash
        ):
            raise RuntimeError("SKU状态文件不属于当前parts.sql或预检方案")
        state.setdefault("rows", {})
        return state
    return {
        "version": 1,
        "source_sha256": source_hash,
        "preview_sha256": preview_hash,
        "rows": {},
    }


def select_items(
    preview: dict[str, Any],
    group_ids: list[str] | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    items = preview["skus"]
    if group_ids:
        wanted = set(group_ids)
        items = [item for item in items if item["sku_group_id"] in wanted]
        missing = wanted - {item["sku_group_id"] for item in items}
        if missing:
            raise RuntimeError(f"预检文件中不存在SKU分组：{sorted(missing)}")
    if limit is not None:
        if limit <= 0:
            raise RuntimeError("--limit必须大于0")
        items = items[:limit]
    return items


def invoice_enabled(value: Any) -> int:
    text = clean_text(value) or ""
    if not text or "不含" in text or text in {"无", "否", "0"}:
        return 0
    return 1 if "含" in text or "是" in text else 0


def shipping_fields(value: Any) -> tuple[str, str | None, str | None]:
    text = preserve_text(value, 255)
    included = bool(text and ("含" in text or "包邮" in text) and "不含" not in text)
    return (
        "include" if included else "exclude",
        text if included else None,
        None if included else text,
    )


def valid_until_fields(value: Any) -> tuple[Any, str | None]:
    text = preserve_text(value, 255)
    parsed = parse_datetime(value)
    return (parsed.date() if parsed else None, text)


def merged_remark(row: dict[str, Any]) -> str | None:
    values = []
    for field in ("remark", "remark_2"):
        text = clean_text(row.get(field))
        if text and text not in values:
            values.append(text)
    return limit_text("；".join(values), 255) if values else None


def row_admin_ids(
    admins: dict[str, int], row: dict[str, Any]
) -> tuple[int | None, int | None]:
    admin_id = resolve_admin_id(admins, actor_name(row))
    update_id = resolve_admin_id(
        admins, row.get("filler_2") or row.get("updater")
    )
    return admin_id, update_id or admin_id


def insert_row(
    cursor: pymysql.cursors.Cursor, table: str, data: dict[str, Any]
) -> int:
    columns = ", ".join(f"`{key}`" for key in data)
    placeholders = ", ".join(["%s"] * len(data))
    cursor.execute(
        f"INSERT INTO `{table}` ({columns}) VALUES ({placeholders})",
        tuple(data.values()),
    )
    return int(cursor.lastrowid)


def update_row(
    cursor: pymysql.cursors.Cursor,
    table: str,
    row_id: int,
    data: dict[str, Any],
) -> None:
    assignments = ", ".join(f"`{key}`=%s" for key in data)
    cursor.execute(
        f"UPDATE `{table}` SET {assignments} WHERE id=%s",
        (*data.values(), row_id),
    )


def existing_id(
    cursor: pymysql.cursors.Cursor,
    table: str,
    row_id: Any = None,
    where: str | None = None,
    params: tuple[Any, ...] = (),
) -> int | None:
    if row_id:
        cursor.execute(f"SELECT id FROM `{table}` WHERE id=%s", (row_id,))
    elif where:
        cursor.execute(
            f"SELECT id FROM `{table}` WHERE {where} ORDER BY id LIMIT 1",
            params,
        )
    else:
        return None
    row = cursor.fetchone()
    return int(row["id"]) if row else None


def ensure_price_type(
    conn: pymysql.connections.Connection, now: datetime
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM yh_price_type WHERE code='retail_price' ORDER BY id LIMIT 1"
        )
        row = cursor.fetchone()
        data = {
            "name": "零售价格",
            "code": "retail_price",
            "sort": 10,
            "status": 1,
            "remark": "parts迁移的SKU零售价格",
            "type": None,
            "update_time": now,
            "delete_time": None,
        }
        if row:
            price_type_id = int(row["id"])
            update_row(cursor, "yh_price_type", price_type_id, data)
            return price_type_id
        data["create_time"] = now
        return insert_row(cursor, "yh_price_type", data)


def ensure_spec_and_value(
    conn: pymysql.connections.Connection,
    spu_id: int,
    nature: str,
    admin_id: int | None,
    create_time: datetime,
    update_time: datetime,
    state_row: dict[str, Any],
) -> tuple[int, int]:
    with conn.cursor() as cursor:
        spec_id = existing_id(
            cursor, "yh_spec", state_row.get("spec_id")
        ) or existing_id(
            cursor,
            "yh_spec",
            where="spu_id=%s AND spec_name='默认' AND delete_time IS NULL",
            params=(spu_id,),
        )
        spec_data = {
            "spu_id": spu_id,
            "spec_code": f"SPEC-PARTS-{spu_id}",
            "spec_name": "默认",
            "unit_id": None,
            "param_type": "枚举",
            "status": 1,
            "sort_order": 0,
            "admin_id": admin_id,
            "delete_time": None,
            "update_time": update_time,
        }
        if spec_id:
            update_row(cursor, "yh_spec", spec_id, spec_data)
        else:
            spec_data["create_time"] = create_time
            spec_id = insert_row(cursor, "yh_spec", spec_data)

        value_id = existing_id(
            cursor, "yh_spec_value", state_row.get("spec_value_id")
        )
        if not value_id:
            cursor.execute(
                """SELECT id,value FROM yh_spec_value
                   WHERE spec_id=%s AND delete_time IS NULL ORDER BY id""",
                (spec_id,),
            )
            for row in cursor.fetchall():
                if normalized_text(row["value"]) == normalized_text(nature):
                    value_id = int(row["id"])
                    break
        value_data = {
            "spec_id": spec_id,
            "value": limit_text(nature, 255) or "默认",
            "extra_price": None,
            "admin_id": admin_id,
            "delete_time": None,
            "update_time": update_time,
        }
        if value_id:
            update_row(cursor, "yh_spec_value", value_id, value_data)
        else:
            value_data["create_time"] = create_time
            value_id = insert_row(cursor, "yh_spec_value", value_data)
        return spec_id, value_id


def sku_data(
    row: dict[str, Any],
    item: dict[str, Any],
    spec_value_id: int,
    admin_id: int | None,
    update_id: int | None,
    status: int,
) -> dict[str, Any]:
    create_time, update_time = source_times(row)
    cost = decimal_value(row.get("purchase_cost"))
    special_enabled = invoice_enabled(row.get("purchase_special_invoice"))
    normal_enabled = invoice_enabled(row.get("purchase_general_invoice"))
    ship_type, ship_include, ship_exclude = shipping_fields(
        row.get("purchase_shipping")
    )
    valid_until, valid_until_txt = valid_until_fields(row.get("quote_validity"))
    images = ordinary_images(row)
    return {
        "sku_code": item["sku_code"],
        "spu_id": int(item["canonical_spu_id"]),
        "warranty": preserve_text(row.get("warranty"), 255),
        "status": status,
        "data_source": DATA_SOURCE,
        "hint": preserve_text(row.get("precautions"), 255),
        "sku_image": images[0]["url"] if images else None,
        "admin_id": admin_id,
        "is_delete": 0,
        "delete_time": None,
        "create_time": create_time,
        "update_time": update_time,
        "detail": detail_html(row.get("product_detail_images")),
        "parameters": clean_text(row.get("technical_params")),
        "shipping_address": preserve_text(row.get("shipping_origin"), 255),
        "delivery_time_desc": preserve_text(row.get("shipping_time"), 100),
        "daily_cutoff_time": preserve_text(row.get("daily_cutoff_time"), 20),
        "retail_price_range": preserve_text(row.get("retail_ladder_price"), 100),
        "retail_tax": preserve_text(row.get("retail_tax"), 50),
        "retail_freight": preserve_text(row.get("retail_shipping"), 50),
        "input_vat_invoice": preserve_text(
            row.get("purchase_special_invoice"), 255
        ),
        "input_plain_invoice": preserve_text(
            row.get("purchase_general_invoice"), 255
        ),
        "procurement_freight": preserve_text(
            row.get("purchase_shipping"), 100
        ),
        "ele_brand": preserve_text(row.get("applicable_elevator_brand"), 255),
        "_skuKey": str(spec_value_id),
        "special_enabled": special_enabled,
        "special_price": cost if special_enabled and cost is not None else None,
        "normal_enabled": normal_enabled,
        "normal_price": cost if normal_enabled and cost is not None else None,
        "ship_type": ship_type,
        "ship_remark_include": ship_include,
        "ship_remark_exclude": ship_exclude,
        "remark": merged_remark(row),
        "price_enabled": 1 if cost is not None else 0,
        "price": cost if cost is not None else 0,
        "valid_until": valid_until,
        "valid_until_txt": valid_until_txt,
        "update_id": update_id,
    }


def save_sku(
    conn: pymysql.connections.Connection,
    data: dict[str, Any],
    state_row: dict[str, Any],
) -> int:
    with conn.cursor() as cursor:
        sku_id = existing_id(
            cursor, "yh_goods_sku", state_row.get("sku_id")
        ) or existing_id(
            cursor,
            "yh_goods_sku",
            where="sku_code=%s",
            params=(data["sku_code"],),
        )
        if sku_id:
            update_row(cursor, "yh_goods_sku", sku_id, data)
            return sku_id
        return insert_row(cursor, "yh_goods_sku", data)


def save_sku_spec_value(
    conn: pymysql.connections.Connection,
    sku_id: int,
    value_id: int,
    create_time: datetime,
    update_time: datetime,
    state_row: dict[str, Any],
) -> int:
    data = {
        "sku_id": sku_id,
        "value_id": value_id,
        "create_time": create_time,
        "update_time": update_time,
        "delete_time": None,
    }
    with conn.cursor() as cursor:
        relation_id = existing_id(
            cursor, "yh_sku_spec_value", state_row.get("sku_spec_value_id")
        ) or existing_id(
            cursor,
            "yh_sku_spec_value",
            where="sku_id=%s AND value_id=%s",
            params=(sku_id, value_id),
        )
        if relation_id:
            update_row(cursor, "yh_sku_spec_value", relation_id, data)
            return relation_id
        return insert_row(cursor, "yh_sku_spec_value", data)


def save_sales_price(
    conn: pymysql.connections.Connection,
    sku_id: int,
    price_type_id: int,
    price: Any,
    admin_id: int | None,
    update_id: int | None,
    create_time: datetime,
    update_time: datetime,
    state_row: dict[str, Any],
) -> int | None:
    parsed = decimal_value(price)
    if parsed is None:
        return None
    data = {
        "sku_id": sku_id,
        "price_type_id": price_type_id,
        "price": parsed,
        "admin_id": admin_id,
        "update_user_id": update_id,
        "create_time": create_time,
        "update_time": update_time,
        "delete_time": None,
    }
    with conn.cursor() as cursor:
        price_id = existing_id(
            cursor, "yh_goods_sku_sales_price", state_row.get("sales_price_id")
        ) or existing_id(
            cursor,
            "yh_goods_sku_sales_price",
            where="sku_id=%s AND price_type_id=%s",
            params=(sku_id, price_type_id),
        )
        if price_id:
            update_row(cursor, "yh_goods_sku_sales_price", price_id, data)
            return price_id
        return insert_row(cursor, "yh_goods_sku_sales_price", data)


def quotation_data(
    row: dict[str, Any],
    spu_id: int,
    sku_id: int,
    supplier_id: int,
    admin_id: int | None,
) -> dict[str, Any]:
    create_time, update_time = source_times(row)
    cost = decimal_value(row.get("purchase_cost"))
    sale_price = decimal_value(row.get("retail_price"))
    special_enabled = invoice_enabled(row.get("purchase_special_invoice"))
    normal_enabled = invoice_enabled(row.get("purchase_general_invoice"))
    valid_until, valid_until_txt = valid_until_fields(row.get("quote_validity"))
    ship_type, ship_include, ship_exclude = shipping_fields(
        row.get("purchase_shipping")
    )
    return {
        "spu_id": spu_id,
        "supplier_id": supplier_id,
        "sku_id": sku_id,
        "brand——": preserve_text(row.get("product_brand"), 255),
        "model": preserve_text(row.get("model"), 255),
        "price_enabled": 1 if cost is not None else 0,
        "price": cost if cost is not None else 0,
        "special_enabled": special_enabled,
        "special_price": cost if special_enabled and cost is not None else None,
        "normal_enabled": normal_enabled,
        "normal_price": cost if normal_enabled and cost is not None else None,
        "sale_price": sale_price if sale_price is not None else 0,
        "lowest_price": None,
        "price_diff": None,
        "valid_until": valid_until,
        "valid_until_txt": valid_until_txt,
        "status": 1 if cost is not None else 0,
        "entry_time": update_time,
        "admin_id": admin_id,
        "delete_time": None,
        "create_time": create_time,
        "update_time": update_time,
        "shipping_address": preserve_text(row.get("shipping_origin"), 255),
        "delivery_time_desc": preserve_text(row.get("shipping_time"), 100),
        "daily_cutoff_time": preserve_text(row.get("daily_cutoff_time"), 20),
        "retail_price_range": preserve_text(row.get("retail_ladder_price"), 100),
        "retail_tax": preserve_text(row.get("retail_tax"), 50),
        "retail_freight": preserve_text(row.get("retail_shipping"), 50),
        "input_vat_invoice": preserve_text(
            row.get("purchase_special_invoice"), 255
        ),
        "input_plain_invoice": preserve_text(
            row.get("purchase_general_invoice"), 255
        ),
        "procurement_freight": preserve_text(
            row.get("purchase_shipping"), 100
        ),
        "warranty": preserve_text(row.get("warranty"), 255),
        "ele_brand": preserve_text(row.get("applicable_elevator_brand"), 255),
        "ship_type": ship_type,
        "ship_remark_include": ship_include,
        "ship_remark_exclude": ship_exclude,
        "remark": merged_remark(row),
        "alert_status": 0,
        "change_desc": None,
        "change_desc_other": None,
        "basis_id": 0,
        "data_source": DATA_SOURCE,
    }


def save_quotation(
    conn: pymysql.connections.Connection,
    data: dict[str, Any],
    quotation_id: Any,
) -> int:
    with conn.cursor() as cursor:
        row_id = existing_id(
            cursor, "yh_goods_quotation", quotation_id
        ) or existing_id(
            cursor,
            "yh_goods_quotation",
            where="sku_id=%s AND supplier_id=%s AND data_source=%s",
            params=(data["sku_id"], data["supplier_id"], DATA_SOURCE),
        )
        if row_id:
            update_row(cursor, "yh_goods_quotation", row_id, data)
            return row_id
        return insert_row(cursor, "yh_goods_quotation", data)


def ensure_empty_or_owned(
    conn: pymysql.connections.Connection, state: dict[str, Any]
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN data_source=%s THEN 0 ELSE 1 END) AS foreign_rows
               FROM yh_goods_sku""",
            (DATA_SOURCE,),
        )
        result = cursor.fetchone()
        count = int(result["total"])
        foreign_rows = int(result["foreign_rows"] or 0)
    if count and foreign_rows and not state["rows"]:
        raise RuntimeError(
            f"目标库已经有{count}条SKU，其中{foreign_rows}条不是本迁移创建，"
            "并且本地没有SKU迁移状态；"
            "为避免覆盖现有商城数据，任务已停止。"
        )


def main() -> int:
    args = parse_args()
    if args.checkpoint_every <= 0:
        raise RuntimeError("--checkpoint-every必须大于0")
    source_path = args.source_sql.expanduser().resolve()
    preview_path = args.preview.expanduser().resolve()
    source_hash = source_file_sha256(source_path)
    preview = load_preview(preview_path, source_path, source_hash)
    items = select_items(preview, args.sku_group_ids, args.limit)
    if not args.execute:
        summary = preview["summary"]
        print(
            "[SKU迁移预览] "
            f"本次选择={len(items)}，全部SKU={summary['sku_groups']}，"
            f"规范SPU={summary['spu_groups']}，来源parts={summary['source_parts']}。"
        )
        print("未修改数据库；确认后使用 --execute。")
        return 0

    preview_hash = preview_fingerprint(preview)
    state = load_state(args.state_file.resolve(), source_hash, preview_hash)
    source_rows = {
        int(row["id"]): row
        for row in source_rows_from_sql(source_path, 1, None, None, None)
    }
    lock = acquire_migration_lock(DEFAULT_LOCK_PATH)
    conn: pymysql.connections.Connection | None = None
    success = failed = quotation_count = 0
    dirty_state = False
    try:
        conn = pymysql.connect(**target_db_config())
        ensure_empty_or_owned(conn, state)
        admins = load_admin_ids(conn)
        price_type_id = ensure_price_type(conn, datetime.now())
        conn.commit()

        for index, item in enumerate(items, start=1):
            group_id = item["sku_group_id"]
            state_row = state["rows"].get(group_id, {})
            database_committed = False
            try:
                row = source_rows[int(item["representative_parts_id"])]
                admin_id, update_id = row_admin_ids(admins, row)
                create_time, update_time = source_times(row)
                spec_id, value_id = ensure_spec_and_value(
                    conn,
                    int(item["canonical_spu_id"]),
                    item["nature"],
                    admin_id,
                    create_time,
                    update_time,
                    state_row,
                )
                data = sku_data(
                    row,
                    item,
                    value_id,
                    admin_id,
                    update_id,
                    args.sku_status,
                )
                sku_id = save_sku(conn, data, state_row)
                relation_id = save_sku_spec_value(
                    conn,
                    sku_id,
                    value_id,
                    create_time,
                    update_time,
                    state_row,
                )
                sales_price_id = save_sales_price(
                    conn,
                    sku_id,
                    price_type_id,
                    item.get("retail_price"),
                    admin_id,
                    update_id,
                    create_time,
                    update_time,
                    state_row,
                )

                old_quote_ids = state_row.get("quotation_ids", {})
                quote_ids: dict[str, int] = {}
                for quote in item["supplier_quotes"]:
                    supplier_id = quote.get("supplier_id")
                    if not supplier_id:
                        continue
                    quote_row = source_rows[int(quote["representative_parts_id"])]
                    quote_admin_id, _ = row_admin_ids(admins, quote_row)
                    quote_data = quotation_data(
                        quote_row,
                        int(item["canonical_spu_id"]),
                        sku_id,
                        int(supplier_id),
                        quote_admin_id,
                    )
                    quote_id = save_quotation(
                        conn,
                        quote_data,
                        old_quote_ids.get(str(supplier_id)),
                    )
                    quote_ids[str(supplier_id)] = quote_id

                conn.commit()
                database_committed = True
                state["rows"][group_id] = {
                    "sku_id": sku_id,
                    "spec_id": spec_id,
                    "spec_value_id": value_id,
                    "sku_spec_value_id": relation_id,
                    "sales_price_id": sales_price_id,
                    "quotation_ids": quote_ids,
                }
                dirty_state = True
                success += 1
                quotation_count += len(quote_ids)
                print(
                    f"[成功] {index}/{len(items)} {item['sku_code']} "
                    f"-> sku.id={sku_id}，spu.id={item['canonical_spu_id']}，"
                    f"规格={item['nature']}，报价={len(quote_ids)}"
                )
                if success % args.checkpoint_every == 0:
                    write_json_atomic(args.state_file.resolve(), state)
                    dirty_state = False
            except Exception as error:
                if not database_committed:
                    conn.rollback()
                failed += 1
                append_error(
                    args.error_file.resolve(),
                    {
                        "sku_group_id": group_id,
                        "sku_code": item["sku_code"],
                        "error": str(error),
                        "time": datetime.now().isoformat(timespec="seconds"),
                    },
                )
                print(
                    f"[失败] {item['sku_code']} | {error}", file=sys.stderr
                )
                if database_committed:
                    write_json_atomic(args.state_file.resolve(), state)
                    raise RuntimeError(
                        f"{item['sku_code']}数据库已提交但状态处理失败，任务停止"
                    ) from error
                if args.stop_on_error:
                    raise

        if dirty_state:
            write_json_atomic(args.state_file.resolve(), state)
        print(
            f"[完成] SKU成功={success}，失败={failed}，供应商报价={quotation_count}"
        )
        return 1 if failed else 0
    finally:
        if conn:
            conn.close()
        release_migration_lock(lock)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"SKU迁移任务启动失败：{error}", file=sys.stderr)
        raise SystemExit(1)
