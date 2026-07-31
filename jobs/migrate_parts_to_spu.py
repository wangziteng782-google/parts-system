#!/usr/bin/env python
"""把 parts 主数据迁移到商城的 SPU、部件、供应商、规格和扩展数据模型。

默认读取用户桌面的全新 parts.sql，只预览：
    python jobs/migrate_parts_to_spu.py --limit 3

首次运行或目标结构需要校正时：
    python jobs/migrate_parts_to_spu.py --prepare-schema

试导三条：
    python jobs/migrate_parts_to_spu.py --execute --limit 3

按 parts.sql 的 5304 条快照导入：
    python jobs/migrate_parts_to_spu.py --execute

重要规则：
1. parts 每一行生成一条 SPU，不按名称、品牌、型号去重。
2. 不修改 yh_goods_spu 原始字段结构，不在目标库保存 source_part_id。
3. 本地 spu_migration_state.json 保存 parts.id 与目标ID的执行状态，
   同时保存 parts.sql 文件指纹，防止SQL文件变化后误用旧状态。
4. parts.product_type 匹配 yh_part.part_name，写入 yh_goods_spu.part_id。
5. 供应商写入 yh_supplier，并由 yh_goods_spu_extra.supplier_id 关联SPU；
   价格、发票、运费、质保和发货信息原样写入 yh_goods_spu_extra。
   本迁移不写 yh_goods_quotation。
6. 普通图片拆到新增的两张SPU图片表；商品详情图片转换成HTML写入
   yh_goods_spu.detail。图片表不保存任何parts来源字段。
7. 每个有 nature 的SPU建立一条“默认”规格，nature 作为规格值；
   尚未生成SKU，因此不写 yh_sku_spec_value。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

import pymysql


PROJECT_DIR = Path(__file__).resolve().parents[1]
TARGET_CONFIG_PATH = PROJECT_DIR / "migration_target.local.json"
CLASSIFICATION_PATH = PROJECT_DIR / "product_classifications.json"
DEFAULT_STATE_PATH = PROJECT_DIR / "jobs" / "spu_migration_state.json"
DEFAULT_ERROR_PATH = PROJECT_DIR / "jobs" / "spu_migration_errors.jsonl"
DEFAULT_LOCK_PATH = PROJECT_DIR / "jobs" / "spu_migration.lock"
DEFAULT_SOURCE_SQL_PATH = Path.home() / "Desktop" / "parts.sql"

PARTS_COLUMNS = [
    "id",
    "sku_code",
    "product_name",
    "product_brand",
    "model",
    "supplier",
    "warranty",
    "applicable_elevator_brand",
    "nature",
    "substitute_model",
    "precautions",
    "category",
    "technical_params",
    "purchase_cost",
    "purchase_special_invoice",
    "purchase_general_invoice",
    "purchase_shipping",
    "retail_price",
    "retail_ladder_price",
    "retail_tax",
    "retail_shipping",
    "remark",
    "daily_cutoff_time",
    "quote_validity",
    "shipping_origin",
    "shipping_time",
    "remark_2",
    "updater",
    "key_part_images",
    "actual_photos",
    "product_image_3",
    "product_image_4",
    "product_image_5",
    "product_image_6",
    "product_image_7",
    "product_image_8",
    "product_image_9",
    "product_image_10",
    "product_detail_images",
    "filler",
    "update_time",
    "filler_2",
    "update_time_2",
    "filler_ip",
    "product_type",
    "variant_groups_initialized",
]

# 用户要求恢复 yh_goods_spu 的原始结构。下面这些字段均为前一版迁移误加字段。
SPU_NON_ORIGINAL_COLUMNS = [
    "source_part_id",
    "supplier",
    "warranty",
    "nature",
    "substitute_model",
    "precautions",
    "category",
    "product_type",
    "purchase_cost",
    "purchase_special_invoice",
    "purchase_general_invoice",
    "purchase_shipping",
    "retail_price",
    "retail_ladder_price",
    "retail_tax",
    "retail_shipping",
    "remark",
    "daily_cutoff_time",
    "quote_validity",
    "shipping_origin",
    "shipping_time",
    "updater",
    "filler",
    "filler_ip",
    "source_variant_groups_initialized",
]

IMAGE_TYPES = [
    ("key_part_images", "关键部位图片", 10),
    ("actual_photos", "实物图照片", 20),
    ("product_image_3", "商品图片3", 30),
    ("product_image_4", "商品图片4", 40),
    ("product_image_5", "商品图片5", 50),
    ("product_image_6", "商品图片6", 60),
    ("product_image_7", "商品图片7", 70),
    ("product_image_8", "商品图片8", 80),
    ("product_image_9", "商品图片9", 90),
    ("product_image_10", "商品图片10", 100),
]

SPU_FIELDS = [
    "spu_code",
    "goods_name",
    "version",
    "brand",
    "unit_id",
    "part_id",
    "status",
    "description",
    "image",
    "detail",
    "parameters",
    "admin_id",
    "delete_time",
    "create_time",
    "update_time",
    "spu_ele_brand",
]

EXTRA_FIELDS = [
    "spu_id",
    "supplier_id",
    "warranty",
    "substitute_model",
    "precautions",
    "category",
    "purchase_cost",
    "purchase_special_invoice",
    "purchase_general_invoice",
    "purchase_shipping",
    "retail_price",
    "retail_ladder_price",
    "retail_tax",
    "retail_shipping",
    "remark",
    "remark_2",
    "daily_cutoff_time",
    "quote_validity",
    "shipping_origin",
    "shipping_time",
    "admin_id",
    "delete_time",
    "create_time",
    "update_time",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="迁移parts到商城SPU业务模型")
    parser.add_argument("--execute", action="store_true", help="实际写入；默认只预览")
    parser.add_argument(
        "--prepare-schema",
        action="store_true",
        help="准备SPU扩展表、图片表和部件树",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-id", type=int, default=1)
    parser.add_argument(
        "--source-sql",
        type=Path,
        default=DEFAULT_SOURCE_SQL_PATH,
        help=f"parts SQL快照路径，默认：{DEFAULT_SOURCE_SQL_PATH}",
    )
    parser.add_argument(
        "--end-id",
        type=int,
        default=None,
        help="本次parts.sql快照最大ID为5326",
    )
    parser.add_argument(
        "--part-id",
        type=int,
        action="append",
        dest="part_ids",
        help="只处理指定parts.id，可重复传入",
    )
    parser.add_argument(
        "--spu-status",
        type=int,
        choices=(0, 1),
        default=1,
        help="默认1上架；如需下架导入可显式传入 --spu-status 0",
    )
    parser.add_argument("--default-unit", default="个")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--error-file", type=Path, default=DEFAULT_ERROR_PATH)
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


def read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )
    try:
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2, default=str)
            file.flush()
            os.fsync(file.fileno())
        for attempt in range(30):
            try:
                os.replace(temp_path, path)
                return
            except PermissionError:
                if attempt == 29:
                    raise
                time.sleep(0.1)
    finally:
        temp_path.unlink(missing_ok=True)


def acquire_migration_lock(path: Path):
    """阻止两个迁移进程同时写数据库和状态文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        handle.close()
        raise RuntimeError(
            "已有另一个SPU迁移任务正在运行，请等待它结束后再执行。"
        )
    return handle


def release_migration_lock(handle) -> None:
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def source_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_state(
    path: Path,
    source_path: Path,
    source_sha256: str,
) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict) or value.get("version") != 4:
        return {
            "version": 4,
            "source_sql": str(source_path.resolve()),
            "source_sha256": source_sha256,
            "rows": {},
        }
    value.setdefault("rows", {})
    previous_sha256 = value.get("source_sha256")
    if previous_sha256 and previous_sha256 != source_sha256 and value["rows"]:
        raise RuntimeError(
            "parts.sql内容已变化，但迁移状态中已有记录。"
            "请先确认旧目标数据和状态文件的处理方式，避免parts.id对应错位。"
        )
    value["source_sql"] = str(source_path.resolve())
    value["source_sha256"] = source_sha256
    return value


def target_db_config() -> dict[str, Any]:
    local_value = read_json(TARGET_CONFIG_PATH)
    local = local_value if isinstance(local_value, dict) else {}
    config = {
        "host": os.getenv("TARGET_DB_HOST", "").strip()
        or str(local.get("host", "")).strip(),
        "port": int(os.getenv("TARGET_DB_PORT", "") or local.get("port", 3306)),
        "user": os.getenv("TARGET_DB_USER", "").strip()
        or str(local.get("user", "")).strip(),
        "password": os.getenv("TARGET_DB_PASSWORD", "")
        or str(local.get("password", "")),
        "database": os.getenv("TARGET_DB_NAME", "").strip()
        or str(local.get("database", "")).strip(),
    }
    missing = [key for key in ("host", "user", "password", "database") if not config[key]]
    if missing:
        raise RuntimeError(
            "目标库配置不完整："
            + "、".join(missing)
            + f"。请设置环境变量或创建 {TARGET_CONFIG_PATH}"
        )
    return {
        **config,
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 30,
    }


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none"} or text in {"-", "—"}:
        return None
    return text


def limit_text(value: Any, length: int) -> str | None:
    text = clean_text(value)
    return text[:length] if text else None


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = clean_text(value)
    if not text:
        return None
    normalized = (
        text.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("/", "-")
        .strip()
    )
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y-%m",
        "%Y",
    ):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    return None


def source_times(row: dict[str, Any]) -> tuple[datetime, datetime]:
    values = [
        item
        for item in (
            parse_datetime(row.get("update_time")),
            parse_datetime(row.get("update_time_2")),
        )
        if item
    ]
    if not values:
        now = datetime.now()
        return now, now
    return min(values), max(values)


def preserve_text(value: Any, length: int) -> str | None:
    """保留扩展业务字段的原始文本；'-' 也是有效业务内容。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    return text[:length]


def parse_image_urls(value: Any) -> list[str]:
    if value is None:
        return []
    raw: Any = value
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"null", "none", "[]"}:
            return []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raw = [text]
    if not isinstance(raw, list):
        raw = [raw]
    urls: list[str] = []
    seen: set[str] = set()
    for item in raw:
        url = clean_text(item)
        if (
            not url
            or url.upper() == "NULL"
            or not re.match(r"^https?://", url, flags=re.I)
        ):
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def detail_html(value: Any) -> str | None:
    urls = parse_image_urls(value)
    if not urls:
        return None
    return "\n".join(
        '<p><img src="{}" alt="商品详情图片" '
        'style="max-width:100%;height:auto;" /></p>'.format(
            html.escape(url, quote=True)
        )
        for url in urls
    )


def image_name(url: str) -> str | None:
    name = Path(unquote(urlparse(url).path)).name.strip()
    return name[:255] if name else None


def ordinary_images(row: dict[str, Any]) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for type_code, type_name, _ in IMAGE_TYPES:
        for sort_order, url in enumerate(parse_image_urls(row.get(type_code))):
            images.append(
                {
                    "type_code": type_code,
                    "type_name": type_name,
                    "url": url,
                    "url_hash": hashlib.sha256(url.encode("utf-8")).hexdigest(),
                    "name": image_name(url),
                    "sort_order": sort_order,
                }
            )
    return images


def split_sql_value_tokens(payload: str, line_number: int) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    in_quote = False
    index = 0
    while index < len(payload):
        char = payload[index]
        if in_quote and char == "\\":
            current.append(char)
            if index + 1 < len(payload):
                current.append(payload[index + 1])
                index += 2
                continue
        if char == "'":
            if in_quote and index + 1 < len(payload) and payload[index + 1] == "'":
                current.extend(("'", "'"))
                index += 2
                continue
            in_quote = not in_quote
            current.append(char)
            index += 1
            continue
        if char == "," and not in_quote:
            tokens.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    if in_quote:
        raise RuntimeError(f"parts.sql第{line_number}行字符串没有闭合")
    tokens.append("".join(current).strip())
    return tokens


def decode_mysql_string(value: str) -> str:
    result: list[str] = []
    escape_map = {
        "0": "\0",
        "'": "'",
        '"': '"',
        "b": "\b",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "Z": "\x1a",
        "\\": "\\",
    }
    index = 0
    while index < len(value):
        char = value[index]
        if char == "'" and index + 1 < len(value) and value[index + 1] == "'":
            result.append("'")
            index += 2
            continue
        if char == "\\" and index + 1 < len(value):
            following = value[index + 1]
            result.append(escape_map.get(following, following))
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def parse_sql_value(token: str, line_number: int) -> Any:
    if token.upper() == "NULL":
        return None
    if token.startswith("'") and token.endswith("'"):
        return decode_mysql_string(token[1:-1])
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"-?\d+(?:\.\d+)?", token):
        return token
    raise RuntimeError(
        f"parts.sql第{line_number}行存在无法识别的值：{token[:80]!r}"
    )


def source_rows_from_sql(
    path: Path,
    start_id: int,
    end_id: int | None,
    part_ids: list[int] | None,
    limit: int | None,
) -> Iterable[dict[str, Any]]:
    if not path.exists():
        raise RuntimeError(f"parts.sql不存在：{path}")

    selected_ids = set(part_ids or [])
    yielded = 0
    insert_count = 0
    pattern = re.compile(r"^INSERT INTO `parts` VALUES \((.*)\);\s*$")
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.startswith("INSERT INTO `parts` VALUES"):
                continue
            insert_count += 1
            match = pattern.match(line.rstrip("\r\n"))
            if not match:
                raise RuntimeError(
                    f"parts.sql第{line_number}行不是受支持的单行INSERT格式"
                )
            tokens = split_sql_value_tokens(match.group(1), line_number)
            if len(tokens) != len(PARTS_COLUMNS):
                raise RuntimeError(
                    f"parts.sql第{line_number}行字段数为{len(tokens)}，"
                    f"预期{len(PARTS_COLUMNS)}"
                )
            values = [parse_sql_value(token, line_number) for token in tokens]
            row = dict(zip(PARTS_COLUMNS, values))
            source_id = int(row["id"])
            if source_id < start_id:
                continue
            if end_id is not None and source_id > end_id:
                continue
            if selected_ids and source_id not in selected_ids:
                continue
            yield row
            yielded += 1
            if limit is not None and yielded >= limit:
                return
    if not insert_count:
        raise RuntimeError(f"parts.sql中没有找到parts数据：{path}")


def actor_name(row: dict[str, Any]) -> str | None:
    # 目标SPU只有一个 admin_id，按确认后的关系仅使用原填报人。
    return clean_text(row.get("filler"))


def build_spu(
    row: dict[str, Any],
    unit_id: int,
    part_id: int,
    admin_id: int | None,
    status: int,
) -> dict[str, Any]:
    images = ordinary_images(row)
    create_time, update_time = source_times(row)
    source_id = int(row["id"])
    return {
        "spu_code": clean_text(row.get("sku_code")) or f"PARTS-SPU-{source_id:07d}",
        "goods_name": clean_text(row.get("product_name")) or f"未命名产品-{source_id}",
        "version": clean_text(row.get("model")),
        "brand": clean_text(row.get("product_brand")),
        "unit_id": unit_id,
        "part_id": part_id,
        "status": status,
        "description": None,
        "image": images[0]["url"] if images else None,
        "detail": detail_html(row.get("product_detail_images")),
        "parameters": clean_text(row.get("technical_params")),
        "admin_id": admin_id,
        "delete_time": None,
        "create_time": create_time,
        "update_time": update_time,
        "spu_ele_brand": clean_text(row.get("applicable_elevator_brand")),
        "_images": images,
    }


def build_extra(
    row: dict[str, Any],
    spu_id: int,
    supplier_id: int | None,
    admin_id: int | None,
) -> dict[str, Any]:
    create_time, update_time = source_times(row)
    return {
        "spu_id": spu_id,
        "supplier_id": supplier_id,
        "warranty": preserve_text(row.get("warranty"), 100),
        "substitute_model": preserve_text(row.get("substitute_model"), 500),
        "precautions": preserve_text(row.get("precautions"), 500),
        "category": preserve_text(row.get("category"), 100),
        "purchase_cost": preserve_text(row.get("purchase_cost"), 100),
        "purchase_special_invoice": preserve_text(
            row.get("purchase_special_invoice"), 100
        ),
        "purchase_general_invoice": preserve_text(
            row.get("purchase_general_invoice"), 100
        ),
        "purchase_shipping": preserve_text(row.get("purchase_shipping"), 100),
        "retail_price": preserve_text(row.get("retail_price"), 100),
        "retail_ladder_price": preserve_text(
            row.get("retail_ladder_price"), 100
        ),
        "retail_tax": preserve_text(row.get("retail_tax"), 100),
        "retail_shipping": preserve_text(row.get("retail_shipping"), 100),
        "remark": preserve_text(row.get("remark"), 100),
        "remark_2": preserve_text(row.get("remark_2"), 100),
        "daily_cutoff_time": preserve_text(row.get("daily_cutoff_time"), 500),
        "quote_validity": preserve_text(row.get("quote_validity"), 100),
        "shipping_origin": preserve_text(row.get("shipping_origin"), 100),
        "shipping_time": preserve_text(row.get("shipping_time"), 500),
        "admin_id": admin_id,
        "delete_time": None,
        "create_time": create_time,
        "update_time": update_time,
    }


def table_columns(cursor: pymysql.cursors.Cursor, table: str) -> set[str]:
    cursor.execute(
        """SELECT COLUMN_NAME FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s""",
        (table,),
    )
    return {row["COLUMN_NAME"] for row in cursor.fetchall()}


def index_exists(cursor: pymysql.cursors.Cursor, table: str, index: str) -> bool:
    cursor.execute(
        """SELECT 1 FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s
           LIMIT 1""",
        (table, index),
    )
    return bool(cursor.fetchone())


def prepare_schema(conn: pymysql.connections.Connection) -> None:
    with conn.cursor() as cursor:
        spu_columns = table_columns(cursor, "yh_goods_spu")
        if index_exists(cursor, "yh_goods_spu", "uk_spu_source_part"):
            print("[结构] 删除SPU来源字段唯一索引")
            cursor.execute("ALTER TABLE yh_goods_spu DROP INDEX uk_spu_source_part")
        for column in SPU_NON_ORIGINAL_COLUMNS:
            if column in spu_columns:
                print(f"[结构] yh_goods_spu 删除非原始字段 {column}")
                cursor.execute(f"ALTER TABLE yh_goods_spu DROP COLUMN `{column}`")

        cursor.execute(
            """CREATE TABLE IF NOT EXISTS yh_spu_image_type (
                id INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'SPU图片类型ID',
                type_code VARCHAR(64) NOT NULL COMMENT '图片类型代码',
                type_name VARCHAR(100) NOT NULL COMMENT '图片类型名称',
                sort_order INT NOT NULL DEFAULT 0 COMMENT '显示顺序',
                status TINYINT(1) NOT NULL DEFAULT 1 COMMENT '状态：1启用，0停用',
                create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                update_time TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                delete_time TIMESTAMP NULL DEFAULT NULL COMMENT '软删除时间',
                PRIMARY KEY (id),
                UNIQUE KEY uk_spu_image_type_code (type_code)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='SPU图片类型表'"""
        )
        type_columns = table_columns(cursor, "yh_spu_image_type")
        if "source_field" in type_columns:
            if index_exists(
                cursor, "yh_spu_image_type", "uk_spu_image_source_field"
            ):
                cursor.execute(
                    "ALTER TABLE yh_spu_image_type "
                    "DROP INDEX uk_spu_image_source_field"
                )
            print("[结构] yh_spu_image_type 删除来源字段 source_field")
            cursor.execute(
                "ALTER TABLE yh_spu_image_type DROP COLUMN source_field"
            )
        if "delete_time" not in type_columns:
            print("[结构] yh_spu_image_type 增加软删除字段 delete_time")
            cursor.execute(
                """ALTER TABLE yh_spu_image_type
                   ADD COLUMN delete_time TIMESTAMP NULL DEFAULT NULL
                   COMMENT '软删除时间' AFTER update_time"""
            )

        cursor.execute(
            """CREATE TABLE IF NOT EXISTS yh_goods_spu_image (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'SPU图片明细ID',
                spu_id INT UNSIGNED NOT NULL COMMENT '关联yh_goods_spu.id',
                image_type_id INT UNSIGNED NOT NULL COMMENT '关联yh_spu_image_type.id',
                url VARCHAR(1000) NOT NULL COMMENT '图片链接',
                url_hash CHAR(64) NOT NULL COMMENT '图片URL哈希，用于同类型内防重',
                name VARCHAR(255) NULL COMMENT '图片文件名',
                sort_order INT NOT NULL DEFAULT 0 COMMENT '同类型图片排序',
                is_cover TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否SPU封面',
                create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                update_time TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                delete_time TIMESTAMP NULL DEFAULT NULL COMMENT '软删除时间',
                PRIMARY KEY (id),
                UNIQUE KEY uk_spu_type_url (spu_id, image_type_id, url_hash),
                KEY idx_spu_image_spu (spu_id),
                KEY idx_spu_image_type (image_type_id),
                CONSTRAINT fk_spu_image_spu FOREIGN KEY (spu_id)
                    REFERENCES yh_goods_spu(id) ON DELETE CASCADE,
                CONSTRAINT fk_spu_image_type FOREIGN KEY (image_type_id)
                    REFERENCES yh_spu_image_type(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='SPU图片明细表'"""
        )
        image_columns = table_columns(cursor, "yh_goods_spu_image")
        if "source_part_id" in image_columns:
            if index_exists(
                cursor, "yh_goods_spu_image", "idx_spu_image_source_part"
            ):
                cursor.execute(
                    "ALTER TABLE yh_goods_spu_image "
                    "DROP INDEX idx_spu_image_source_part"
                )
            print("[结构] yh_goods_spu_image 删除来源字段 source_part_id")
            cursor.execute(
                "ALTER TABLE yh_goods_spu_image DROP COLUMN source_part_id"
            )
        if "source_field" in image_columns:
            print("[结构] yh_goods_spu_image 删除来源字段 source_field")
            cursor.execute(
                "ALTER TABLE yh_goods_spu_image DROP COLUMN source_field"
            )

        cursor.execute(
            """CREATE TABLE IF NOT EXISTS yh_goods_spu_extra (
                id BIGINT NOT NULL AUTO_INCREMENT COMMENT 'SPU扩展数据主键',
                spu_id INT UNSIGNED NOT NULL COMMENT '关联yh_goods_spu.id',
                supplier_id BIGINT NULL COMMENT '关联yh_supplier.id',
                warranty VARCHAR(100) NULL COMMENT '质保',
                substitute_model VARCHAR(500) NULL COMMENT '替代型号',
                precautions VARCHAR(500) NULL COMMENT '注意事项',
                category VARCHAR(100) NULL COMMENT '原品类归属',
                purchase_cost VARCHAR(100) NULL COMMENT '采购成本价',
                purchase_special_invoice VARCHAR(100) NULL COMMENT '进项专票',
                purchase_general_invoice VARCHAR(100) NULL COMMENT '进项普票',
                purchase_shipping VARCHAR(100) NULL COMMENT '采购运费',
                retail_price VARCHAR(100) NULL COMMENT '零售价格',
                retail_ladder_price VARCHAR(100) NULL COMMENT '零售阶梯价',
                retail_tax VARCHAR(100) NULL COMMENT '零售税费',
                retail_shipping VARCHAR(100) NULL COMMENT '零售运费',
                remark VARCHAR(100) NULL COMMENT '备注',
                remark_2 VARCHAR(100) NULL COMMENT '备注2',
                daily_cutoff_time VARCHAR(500) NULL COMMENT '每日截单时间',
                quote_validity VARCHAR(100) NULL COMMENT '报价有效期',
                shipping_origin VARCHAR(100) NULL COMMENT '发货地',
                shipping_time VARCHAR(500) NULL COMMENT '发货时间',
                admin_id INT NULL COMMENT '创建管理员ID，对应yh_admin_user.id',
                delete_time TIMESTAMP NULL DEFAULT NULL COMMENT '删除时间',
                create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                update_time TIMESTAMP NULL DEFAULT NULL
                    ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                PRIMARY KEY (id),
                UNIQUE KEY uq_goods_spu_extra_spu (spu_id),
                KEY idx_goods_spu_extra_supplier (supplier_id),
                KEY idx_goods_spu_extra_admin (admin_id),
                CONSTRAINT fk_goods_spu_extra_spu FOREIGN KEY (spu_id)
                    REFERENCES yh_goods_spu(id) ON DELETE CASCADE,
                CONSTRAINT fk_goods_spu_extra_supplier FOREIGN KEY (supplier_id)
                    REFERENCES yh_supplier(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='SPU原系统扩展业务数据'"""
        )

        cursor.execute(
            """SELECT id FROM yh_spu_image_type
               WHERE type_code='product_detail_images'"""
        )
        obsolete = cursor.fetchone()
        if obsolete:
            cursor.execute(
                "DELETE FROM yh_goods_spu_image WHERE image_type_id=%s",
                (obsolete["id"],),
            )
            cursor.execute(
                "DELETE FROM yh_spu_image_type WHERE id=%s", (obsolete["id"],)
            )
        for code, name, sort_order in IMAGE_TYPES:
            cursor.execute(
                """INSERT INTO yh_spu_image_type
                       (type_code, type_name, sort_order, status, delete_time)
                   VALUES (%s, %s, %s, 1, NULL)
                   ON DUPLICATE KEY UPDATE
                       type_name=VALUES(type_name),
                       sort_order=VALUES(sort_order),
                       status=1,
                       delete_time=NULL""",
                (code, name, sort_order),
            )
    conn.commit()
    prepare_part_tree(conn)


def prepare_part_tree(conn: pymysql.connections.Connection) -> None:
    tree = read_json(CLASSIFICATION_PATH)
    if not isinstance(tree, list) or not tree:
        raise RuntimeError(f"分类JSON格式错误：{CLASSIFICATION_PATH}")

    def ensure_category(
        cursor: pymysql.cursors.Cursor,
        parent_id: int,
        name: str,
        level: int,
        sort_order: int,
    ) -> int:
        cursor.execute(
            """SELECT id FROM yh_part_category
               WHERE parent_id=%s AND name=%s AND delete_time IS NULL
               ORDER BY id LIMIT 1""",
            (parent_id, name),
        )
        row = cursor.fetchone()
        if row:
            category_id = int(row["id"])
            cursor.execute(
                """UPDATE yh_part_category
                   SET level=%s, sort_order=%s, status=1, update_time=NOW()
                   WHERE id=%s""",
                (level, sort_order, category_id),
            )
            return category_id
        cursor.execute(
            """INSERT INTO yh_part_category
                   (parent_id, name, part_type, status, level, sort_order,
                    admin_id, delete_time, create_time, update_time, update_id)
               VALUES (%s, %s, NULL, 1, %s, %s,
                       NULL, NULL, NOW(), NOW(), NULL)""",
            (parent_id, name, level, sort_order),
        )
        return int(cursor.lastrowid)

    def ensure_part(
        cursor: pymysql.cursors.Cursor,
        category_id: int,
        name: str,
        code: str,
    ) -> None:
        cursor.execute(
            """SELECT id FROM yh_part
               WHERE part_category_id=%s AND part_name=%s AND delete_time IS NULL
               ORDER BY id LIMIT 1""",
            (category_id, name),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """UPDATE yh_part
                   SET part_code=%s, status=1, data_source='parts分类JSON',
                       update_time=NOW()
                   WHERE id=%s""",
                (code, row["id"]),
            )
        else:
            cursor.execute(
                """INSERT INTO yh_part
                       (part_code, part_name, part_type, part_category_id,
                        status, data_source, admin_id, delete_time,
                        create_time, update_time)
                   VALUES (%s, %s, NULL, %s, 1, 'parts分类JSON',
                           NULL, NULL, NOW(), NOW())""",
                (code, name, category_id),
            )

    counter = 0
    with conn.cursor() as cursor:
        for first_order, first in enumerate(tree):
            first_name = clean_text(first.get("name"))
            if not first_name:
                continue
            first_id = ensure_category(cursor, 0, first_name, 1, first_order)
            for second_order, second in enumerate(first.get("children") or []):
                second_name = clean_text(second.get("name"))
                if not second_name:
                    continue
                second_id = ensure_category(
                    cursor, first_id, second_name, 2, second_order
                )
                for third in second.get("children") or []:
                    third_name = clean_text(third)
                    if third_name:
                        counter += 1
                        ensure_part(
                            cursor, second_id, third_name, f"DT-P-{counter:04d}"
                        )
    conn.commit()
    print("[部件] JSON部件分类和三级部件准备完成")


def ensure_schema_ready(conn: pymysql.connections.Connection) -> None:
    with conn.cursor() as cursor:
        columns = table_columns(cursor, "yh_goods_spu")
        remaining = sorted(set(SPU_NON_ORIGINAL_COLUMNS) & columns)
        if remaining:
            raise RuntimeError(
                "yh_goods_spu仍有非原始字段："
                + "、".join(remaining)
                + "，请先运行 --prepare-schema"
            )
        for table in (
            "yh_spu_image_type",
            "yh_goods_spu_image",
            "yh_goods_spu_extra",
        ):
            cursor.execute(
                """SELECT 1 FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s""",
                (table,),
            )
            if not cursor.fetchone():
                raise RuntimeError(f"缺少{table}，请先运行 --prepare-schema")
        image_type_columns = table_columns(cursor, "yh_spu_image_type")
        if "delete_time" not in image_type_columns:
            raise RuntimeError(
                "yh_spu_image_type缺少delete_time，请先运行 --prepare-schema"
            )


def ensure_default_unit(conn: pymysql.connections.Connection, name: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """SELECT id FROM yh_unit
               WHERE name=%s AND delete_time IS NULL ORDER BY id LIMIT 1""",
            (name,),
        )
        row = cursor.fetchone()
        if row:
            return int(row["id"])
        cursor.execute(
            """INSERT INTO yh_unit (name, admin_id, create_time, update_time)
               VALUES (%s, NULL, NOW(), NOW())""",
            (name,),
        )
        unit_id = int(cursor.lastrowid)
    conn.commit()
    return unit_id


def load_part_ids(conn: pymysql.connections.Connection) -> dict[str, int]:
    with conn.cursor() as cursor:
        cursor.execute(
            """SELECT id,part_name FROM yh_part
               WHERE status=1 AND delete_time IS NULL ORDER BY id"""
        )
        result: dict[str, int] = {}
        for row in cursor.fetchall():
            name = row["part_name"]
            if name in result:
                raise RuntimeError(f"三级部件名称重复：{name}")
            result[name] = int(row["id"])
        return result


def load_admin_ids(conn: pymysql.connections.Connection) -> dict[str, int]:
    def normalize(value: Any) -> str:
        return re.sub(r"\s+", "", clean_text(value) or "").lower()

    result: dict[str, int] = {}
    with conn.cursor() as cursor:
        cursor.execute(
            """SELECT id,username,nickname FROM yh_admin_user
               WHERE is_delete=0 ORDER BY id"""
        )
        for row in cursor.fetchall():
            for value in (row["username"], row["nickname"]):
                key = normalize(value)
                if key:
                    result.setdefault(key, int(row["id"]))
    if "lwl" in result:
        result.setdefault("李文乐", result["lwl"])
    return result


def resolve_admin_id(admins: dict[str, int], value: Any) -> int | None:
    key = re.sub(r"\s+", "", clean_text(value) or "").lower()
    return admins.get(key) if key else None


def ensure_supplier(
    conn: pymysql.connections.Connection,
    supplier_name: str,
    admin_id: int | None,
    create_time: datetime,
    update_time: datetime,
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """SELECT id FROM yh_supplier
               WHERE supplier_name=%s AND delete_time IS NULL
               ORDER BY id LIMIT 1""",
            (supplier_name,),
        )
        row = cursor.fetchone()
        if row:
            return int(row["id"])
        digest = hashlib.sha1(supplier_name.encode("utf-8")).hexdigest()[:10].upper()
        cursor.execute(
            """INSERT INTO yh_supplier
                   (supplier_code,supplier_name,contact_person,contact_phone,
                    province,city,area,address,cooperation_status,remark,
                    admin_id,delete_time,create_time,update_time)
               VALUES (%s,%s,NULL,NULL,NULL,NULL,NULL,NULL,1,NULL,
                       %s,NULL,%s,%s)""",
            (f"GY-PARTS-{digest}", supplier_name, admin_id, create_time, update_time),
        )
        return int(cursor.lastrowid)


def load_image_type_ids(conn: pymysql.connections.Connection) -> dict[str, int]:
    with conn.cursor() as cursor:
        cursor.execute(
            """SELECT id,type_code FROM yh_spu_image_type
               WHERE status=1 AND delete_time IS NULL"""
        )
        return {row["type_code"]: int(row["id"]) for row in cursor.fetchall()}


def record_exists(
    conn: pymysql.connections.Connection, table: str, record_id: Any
) -> bool:
    if not record_id:
        return False
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT 1 FROM `{table}` WHERE id=%s", (record_id,))
        return bool(cursor.fetchone())


def save_spu(
    conn: pymysql.connections.Connection,
    data: dict[str, Any],
    existing_id: int | None,
) -> int:
    values = [data[field] for field in SPU_FIELDS]
    with conn.cursor() as cursor:
        if existing_id and record_exists(conn, "yh_goods_spu", existing_id):
            clause = ", ".join(f"`{field}`=%s" for field in SPU_FIELDS)
            cursor.execute(
                f"UPDATE yh_goods_spu SET {clause} WHERE id=%s",
                [*values, existing_id],
            )
            return existing_id
        columns = ", ".join(f"`{field}`" for field in SPU_FIELDS)
        placeholders = ", ".join(["%s"] * len(SPU_FIELDS))
        cursor.execute(
            f"INSERT INTO yh_goods_spu ({columns}) VALUES ({placeholders})",
            values,
        )
        return int(cursor.lastrowid)


def save_extra(
    conn: pymysql.connections.Connection,
    data: dict[str, Any],
) -> int:
    values = [data[field] for field in EXTRA_FIELDS]
    with conn.cursor() as cursor:
        columns = ", ".join(f"`{field}`" for field in EXTRA_FIELDS)
        placeholders = ", ".join(["%s"] * len(EXTRA_FIELDS))
        update_fields = [field for field in EXTRA_FIELDS if field != "spu_id"]
        update_clause = ", ".join(
            f"`{field}`=VALUES(`{field}`)" for field in update_fields
        )
        cursor.execute(
            f"""INSERT INTO yh_goods_spu_extra ({columns})
                VALUES ({placeholders})
                ON DUPLICATE KEY UPDATE {update_clause}""",
            values,
        )
        cursor.execute(
            "SELECT id FROM yh_goods_spu_extra WHERE spu_id=%s",
            (data["spu_id"],),
        )
        return int(cursor.fetchone()["id"])


def save_default_spec(
    conn: pymysql.connections.Connection,
    spu_id: int,
    nature: Any,
    admin_id: int | None,
    create_time: datetime,
    update_time: datetime,
) -> tuple[int | None, int | None]:
    value = limit_text(nature, 255)
    if not value:
        return None, None

    with conn.cursor() as cursor:
        cursor.execute(
            """SELECT id FROM yh_spec
               WHERE spu_id=%s AND spec_name='默认' AND delete_time IS NULL
               ORDER BY id LIMIT 1""",
            (spu_id,),
        )
        row = cursor.fetchone()
        if row:
            spec_id = int(row["id"])
            cursor.execute(
                """UPDATE yh_spec
                   SET spec_code=%s,unit_id=NULL,param_type='枚举',
                       status=1,sort_order=0,admin_id=%s,
                       delete_time=NULL,update_time=%s
                   WHERE id=%s""",
                (f"SPEC-PARTS-{spu_id}", admin_id, update_time, spec_id),
            )
        else:
            cursor.execute(
                """INSERT INTO yh_spec
                       (spu_id,spec_code,spec_name,unit_id,param_type,status,
                        sort_order,admin_id,delete_time,create_time,update_time)
                   VALUES (%s,%s,'默认',NULL,'枚举',1,0,%s,NULL,%s,%s)""",
                (
                    spu_id,
                    f"SPEC-PARTS-{spu_id}",
                    admin_id,
                    create_time,
                    update_time,
                ),
            )
            spec_id = int(cursor.lastrowid)

        cursor.execute(
            """SELECT id FROM yh_spec_value
               WHERE spec_id=%s AND delete_time IS NULL
               ORDER BY id""",
            (spec_id,),
        )
        value_rows = cursor.fetchall()
        if value_rows:
            value_id = int(value_rows[0]["id"])
            cursor.execute(
                """UPDATE yh_spec_value
                   SET value=%s,extra_price=NULL,admin_id=%s,
                       delete_time=NULL,update_time=%s
                   WHERE id=%s""",
                (value, admin_id, update_time, value_id),
            )
            for duplicate in value_rows[1:]:
                cursor.execute(
                    """UPDATE yh_spec_value
                       SET delete_time=NOW(),update_time=NOW()
                       WHERE id=%s""",
                    (duplicate["id"],),
                )
        else:
            cursor.execute(
                """INSERT INTO yh_spec_value
                       (spec_id,value,extra_price,admin_id,delete_time,
                        create_time,update_time)
                   VALUES (%s,%s,NULL,%s,NULL,%s,%s)""",
                (spec_id, value, admin_id, create_time, update_time),
            )
            value_id = int(cursor.lastrowid)
    return spec_id, value_id


def save_images(
    conn: pymysql.connections.Connection,
    spu_id: int,
    images: list[dict[str, Any]],
    type_ids: dict[str, int],
) -> None:
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM yh_goods_spu_image WHERE spu_id=%s", (spu_id,))
        for global_order, image in enumerate(images):
            type_id = type_ids.get(image["type_code"])
            if not type_id:
                raise RuntimeError(f"缺少图片类型：{image['type_code']}")
            cursor.execute(
                """INSERT INTO yh_goods_spu_image
                       (spu_id,image_type_id,url,url_hash,name,sort_order,
                        is_cover,create_time,update_time,delete_time)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),NULL,NULL)""",
                (
                    spu_id,
                    type_id,
                    image["url"],
                    image["url_hash"],
                    image["name"],
                    image["sort_order"],
                    1 if global_order == 0 else 0,
                ),
            )


def append_error(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def preview_row(row: dict[str, Any]) -> None:
    images = ordinary_images(row)
    print(
        json.dumps(
            {
                "parts_id": row["id"],
                "spu": {
                    "spu_code": clean_text(row.get("sku_code"))
                    or f"PARTS-SPU-{int(row['id']):07d}",
                    "goods_name": row.get("product_name"),
                    "version": row.get("model"),
                    "brand": row.get("product_brand"),
                    "part_name": row.get("product_type"),
                    "parameters": row.get("technical_params"),
                },
                "supplier": clean_text(row.get("supplier")),
                "default_spec": {
                    "spec_name": "默认",
                    "spec_value": clean_text(row.get("nature")),
                },
                "extra": {
                    "warranty": row.get("warranty"),
                    "substitute_model": row.get("substitute_model"),
                    "precautions": row.get("precautions"),
                    "category": row.get("category"),
                    "purchase_cost": row.get("purchase_cost"),
                    "retail_price": row.get("retail_price"),
                    "shipping_origin": row.get("shipping_origin"),
                    "shipping_time": row.get("shipping_time"),
                },
                "ordinary_image_count": len(images),
                "detail_image_count": len(
                    parse_image_urls(row.get("product_detail_images"))
                ),
            },
            ensure_ascii=False,
            default=str,
        )
    )


def main() -> int:
    args = parse_args()
    if args.limit is not None and args.limit <= 0:
        raise RuntimeError("--limit必须大于0")

    source_path = args.source_sql.expanduser().resolve()
    if not source_path.exists():
        raise RuntimeError(f"parts.sql不存在：{source_path}")
    source_sha256 = source_file_sha256(source_path)
    target_conn: pymysql.connections.Connection | None = None
    migration_lock = (
        acquire_migration_lock(DEFAULT_LOCK_PATH)
        if args.execute or args.prepare_schema
        else None
    )
    try:
        rows = list(
            source_rows_from_sql(
                source_path,
                args.start_id,
                args.end_id,
                args.part_ids,
                args.limit,
            )
        )
        if not args.execute and not args.prepare_schema:
            print(
                f"[预览] 来源={source_path}，SHA256={source_sha256[:12]}...，"
                f"选中={len(rows)}条，不修改目标数据库"
            )
            for row in rows:
                preview_row(row)
            return 0

        target_conn = pymysql.connect(**target_db_config())
        if args.prepare_schema:
            prepare_schema(target_conn)
            print("[结构] SPU扩展表、图片表和部件树准备完成")
            if not args.execute:
                return 0

        ensure_schema_ready(target_conn)
        if not rows:
            print("没有符合条件的parts数据")
            return 0

        state = load_state(
            args.state_file,
            source_path,
            source_sha256,
        )
        unit_id = ensure_default_unit(target_conn, args.default_unit)
        parts = load_part_ids(target_conn)
        admins = load_admin_ids(target_conn)
        image_types = load_image_type_ids(target_conn)
        success = failed = image_count = 0

        for row in rows:
            source_id = int(row["id"])
            state_row = state["rows"].get(str(source_id), {})
            database_committed = False
            try:
                product_type = clean_text(row.get("product_type"))
                part_id = parts.get(product_type or "")
                if not part_id:
                    raise RuntimeError(f"无法匹配三级部件：{product_type!r}")
                admin_id = resolve_admin_id(admins, actor_name(row))
                spu = build_spu(
                    row, unit_id, part_id, admin_id, args.spu_status
                )
                spu_id = save_spu(
                    target_conn, spu, state_row.get("spu_id")
                )
                create_time, update_time = source_times(row)
                supplier_name = clean_text(row.get("supplier"))
                supplier_id = (
                    ensure_supplier(
                        target_conn,
                        supplier_name,
                        admin_id,
                        create_time,
                        update_time,
                    )
                    if supplier_name
                    else None
                )
                extra = build_extra(row, spu_id, supplier_id, admin_id)
                extra_id = save_extra(target_conn, extra)
                spec_id, spec_value_id = save_default_spec(
                    target_conn,
                    spu_id,
                    row.get("nature"),
                    admin_id,
                    create_time,
                    update_time,
                )
                save_images(target_conn, spu_id, spu["_images"], image_types)
                target_conn.commit()
                database_committed = True
                state["rows"][str(source_id)] = {
                    "spu_id": spu_id,
                    "supplier_id": supplier_id,
                    "extra_id": extra_id,
                    "spec_id": spec_id,
                    "spec_value_id": spec_value_id,
                }
                write_json_atomic(args.state_file, state)
                success += 1
                image_count += len(spu["_images"])
                print(
                    f"[成功] parts.id={source_id} -> spu.id={spu_id}, "
                    f"supplier.id={supplier_id}, extra.id={extra_id}, "
                    f"spec.id={spec_id}, spec_value.id={spec_value_id}, "
                    f"图片={len(spu['_images'])}"
                )
            except Exception as error:
                if not database_committed:
                    target_conn.rollback()
                failed += 1
                append_error(
                    args.error_file,
                    {
                        "parts_id": source_id,
                        "error": str(error),
                        "time": datetime.now().isoformat(timespec="seconds"),
                    },
                )
                print(f"[失败] parts.id={source_id} | {error}", file=sys.stderr)
                if database_committed:
                    raise RuntimeError(
                        f"parts.id={source_id} 已提交到数据库，但状态文件保存失败；"
                        "任务已停止，请先核对并修复状态后再重跑。"
                    ) from error
                if args.stop_on_error:
                    raise
        print(
            f"[完成] SPU成功={success}，失败={failed}，普通图片={image_count}"
        )
        return 1 if failed else 0
    finally:
        if target_conn:
            target_conn.close()
        release_migration_lock(migration_lock)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"迁移任务启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
