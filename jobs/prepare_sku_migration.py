#!/usr/bin/env python
"""生成方案B的SKU迁移预检清单，不修改目标数据库。

默认输出：
  jobs/sku_migration_preview.json
  jobs/sku_migration_preview.csv

分组规则：
1. 规范SPU：产品分类 + 产品名称 + 品牌 + 型号。
2. 型号为空时不与其他产品合并，避免误归并。
3. SKU：规范SPU + 性质（默认规格值）+ 初始零售价。
4. 供应商不参与SKU唯一键，同一SKU可包含多个供应商报价来源。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from migrate_parts_to_spu import (
    DEFAULT_SOURCE_SQL_PATH,
    DEFAULT_STATE_PATH,
    clean_text,
    source_file_sha256,
    source_rows_from_sql,
    source_times,
    write_json_atomic,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_JSON_PATH = PROJECT_DIR / "jobs" / "sku_migration_preview.json"
DEFAULT_CSV_PATH = PROJECT_DIR / "jobs" / "sku_migration_preview.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成parts到ytgoods SKU的方案B预检映射"
    )
    parser.add_argument(
        "--source-sql", type=Path, default=DEFAULT_SOURCE_SQL_PATH
    )
    parser.add_argument("--spu-state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_PATH)
    return parser.parse_args()


def normalized_text(value: Any) -> str:
    text = clean_text(value) or ""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def display_text(value: Any, default: str = "") -> str:
    return clean_text(value) or default


def decimal_value(value: Any) -> Decimal | None:
    text = clean_text(value)
    if not text:
        return None
    normalized = (
        unicodedata.normalize("NFKC", text)
        .replace(",", "")
        .replace("￥", "")
        .replace("¥", "")
        .replace("元", "")
        .strip()
    )
    normalized = re.sub(
        r"/(?:条|米|个|套|件|台|只|根|块|张|公斤|千克|kg)$",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", normalized):
        return None
    try:
        return Decimal(normalized).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def decimal_token(value: Any) -> str:
    parsed = decimal_value(value)
    return f"{parsed:.2f}" if parsed is not None else "__待定价__"


def spu_group_key(row: dict[str, Any]) -> tuple[str, ...]:
    model = normalized_text(row.get("model"))
    if not model:
        return ("__无型号__", str(int(row["id"])))
    return (
        normalized_text(row.get("product_type")),
        normalized_text(row.get("product_name")),
        normalized_text(row.get("product_brand")),
        model,
    )


def nature_value(row: dict[str, Any]) -> str:
    return display_text(row.get("nature"), "默认")


def nature_token(row: dict[str, Any]) -> str:
    return normalized_text(row.get("nature")) or "默认"


def stable_hash(parts: tuple[str, ...], length: int = 16) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:length].upper()


def latest_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(rows, key=lambda row: (source_times(row)[1], int(row["id"])))


def load_spu_state(
    path: Path, source_path: Path, source_hash: str
) -> dict[str, dict[str, Any]]:
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("source_sha256") != source_hash:
        raise RuntimeError("SPU迁移状态与当前parts.sql文件指纹不一致")
    if Path(state.get("source_sql", "")).resolve() != source_path.resolve():
        raise RuntimeError("SPU迁移状态不属于当前parts.sql文件")
    rows = state.get("rows")
    if not isinstance(rows, dict):
        raise RuntimeError("SPU迁移状态缺少rows映射")
    return rows


def build_preview(
    source_rows: list[dict[str, Any]],
    spu_state: dict[str, dict[str, Any]],
    source_path: Path,
    source_hash: str,
) -> dict[str, Any]:
    source_ids = {str(int(row["id"])) for row in source_rows}
    missing_state = sorted(int(value) for value in source_ids - spu_state.keys())
    if missing_state:
        raise RuntimeError(
            f"有{len(missing_state)}条parts没有SPU状态，示例：{missing_state[:20]}"
        )

    spu_groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        spu_groups[spu_group_key(row)].append(row)

    sku_items: list[dict[str, Any]] = []
    canonical_spus: list[dict[str, Any]] = []
    invalid_retail_prices: list[dict[str, Any]] = []
    invalid_purchase_costs: list[dict[str, Any]] = []
    source_coverage: set[int] = set()

    for spu_key, group_rows in sorted(
        spu_groups.items(), key=lambda item: min(int(row["id"]) for row in item[1])
    ):
        canonical_row = min(group_rows, key=lambda row: int(row["id"]))
        canonical_source_id = int(canonical_row["id"])
        canonical_state = spu_state[str(canonical_source_id)]
        canonical_spu_id = int(canonical_state["spu_id"])
        spu_hash = stable_hash(spu_key)

        sku_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in group_rows:
            sku_groups[(nature_token(row), decimal_token(row.get("retail_price")))].append(
                row
            )

        canonical_spus.append(
            {
                "spu_group_id": spu_hash,
                "canonical_parts_id": canonical_source_id,
                "canonical_spu_id": canonical_spu_id,
                "product_type": display_text(canonical_row.get("product_type")),
                "product_name": display_text(canonical_row.get("product_name")),
                "product_brand": display_text(canonical_row.get("product_brand")),
                "model": display_text(canonical_row.get("model")),
                "source_parts_ids": sorted(int(row["id"]) for row in group_rows),
                "source_spu_ids": sorted(
                    int(spu_state[str(int(row["id"]))]["spu_id"])
                    for row in group_rows
                ),
                "sku_count": len(sku_groups),
            }
        )

        for (nature_key, retail_key), sku_rows in sorted(
            sku_groups.items(),
            key=lambda item: min(int(row["id"]) for row in item[1]),
        ):
            representative = latest_row(sku_rows)
            representative_id = int(representative["id"])
            source_parts_ids = sorted(int(row["id"]) for row in sku_rows)
            source_coverage.update(source_parts_ids)
            supplier_items: dict[int | None, list[dict[str, Any]]] = defaultdict(list)
            for row in sku_rows:
                state_row = spu_state[str(int(row["id"]))]
                supplier_id = state_row.get("supplier_id")
                supplier_items[int(supplier_id) if supplier_id else None].append(row)

                if clean_text(row.get("retail_price")) and decimal_value(
                    row.get("retail_price")
                ) is None:
                    invalid_retail_prices.append(
                        {
                            "parts_id": int(row["id"]),
                            "value": str(row.get("retail_price")),
                        }
                    )
                if clean_text(row.get("purchase_cost")) and decimal_value(
                    row.get("purchase_cost")
                ) is None:
                    invalid_purchase_costs.append(
                        {
                            "parts_id": int(row["id"]),
                            "value": str(row.get("purchase_cost")),
                        }
                    )

            supplier_quotes = []
            for supplier_id, supplier_rows in sorted(
                supplier_items.items(),
                key=lambda item: (
                    item[0] is None,
                    item[0] if item[0] is not None else 0,
                ),
            ):
                quote_row = latest_row(supplier_rows)
                supplier_quotes.append(
                    {
                        "supplier_id": supplier_id,
                        "supplier_name": display_text(quote_row.get("supplier")),
                        "representative_parts_id": int(quote_row["id"]),
                        "source_parts_ids": sorted(
                            int(row["id"]) for row in supplier_rows
                        ),
                        "purchase_cost": display_text(
                            quote_row.get("purchase_cost")
                        ),
                        "retail_price": display_text(quote_row.get("retail_price")),
                    }
                )

            sku_hash = stable_hash((spu_hash, nature_key, retail_key), 20)
            sku_items.append(
                {
                    "sku_group_id": sku_hash,
                    "sku_code": f"SKU-P-{sku_hash[:12]}",
                    "canonical_spu_id": canonical_spu_id,
                    "canonical_parts_id": canonical_source_id,
                    "representative_parts_id": representative_id,
                    "nature": nature_value(representative),
                    "retail_price": (
                        retail_key if retail_key != "__待定价__" else None
                    ),
                    "raw_retail_price": display_text(
                        representative.get("retail_price")
                    ),
                    "source_parts_ids": source_parts_ids,
                    "source_spu_ids": sorted(
                        int(spu_state[str(source_id)]["spu_id"])
                        for source_id in source_parts_ids
                    ),
                    "supplier_quotes": supplier_quotes,
                }
            )

    multi_source_skus = [
        item for item in sku_items if len(item["source_parts_ids"]) > 1
    ]
    multi_supplier_skus = [
        item
        for item in sku_items
        if len([q for q in item["supplier_quotes"] if q["supplier_id"]]) > 1
    ]
    sku_count_by_spu = Counter(item["canonical_spu_id"] for item in sku_items)

    return {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_sql": str(source_path),
        "source_sha256": source_hash,
        "rules": {
            "spu_key": "产品分类+产品名称+品牌+型号；型号为空时按parts.id隔离",
            "sku_key": "规范SPU+性质+初始零售价",
            "canonical_spu": "同一SPU分组中parts.id最小的一条",
            "representative_row": "同一SKU分组中更新时间最新的一条",
            "supplier": "供应商不参与SKU去重，每个供应商生成独立报价",
            "unmatched_fields": "不新增SKU扩展表，不能匹配的字段不重复写入",
        },
        "summary": {
            "source_parts": len(source_rows),
            "spu_groups": len(canonical_spus),
            "sku_groups": len(sku_items),
            "merged_source_rows": len(source_rows) - len(sku_items),
            "multi_source_skus": len(multi_source_skus),
            "multi_supplier_skus": len(multi_supplier_skus),
            "spus_with_multiple_skus": sum(
                1 for count in sku_count_by_spu.values() if count > 1
            ),
            "max_skus_per_spu": max(sku_count_by_spu.values(), default=0),
            "invalid_retail_price_rows": len(invalid_retail_prices),
            "invalid_purchase_cost_rows": len(invalid_purchase_costs),
            "sku_without_retail_price": sum(
                1 for item in sku_items if item["retail_price"] is None
            ),
            "sku_without_supplier": sum(
                1
                for item in sku_items
                if not any(
                    quote["supplier_id"] is not None
                    for quote in item["supplier_quotes"]
                )
            ),
            "supplier_quotation_rows": sum(
                1
                for item in sku_items
                for quote in item["supplier_quotes"]
                if quote["supplier_id"] is not None
            ),
            "source_coverage": len(source_coverage),
        },
        "invalid_retail_prices": invalid_retail_prices,
        "invalid_purchase_costs": invalid_purchase_costs,
        "canonical_spus": canonical_spus,
        "skus": sku_items,
    }


def write_csv(path: Path, preview: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "sku_group_id",
                "sku_code",
                "canonical_spu_id",
                "canonical_parts_id",
                "representative_parts_id",
                "nature",
                "retail_price",
                "source_parts_ids",
                "source_spu_ids",
                "supplier_count",
                "suppliers",
                "status",
            ],
        )
        writer.writeheader()
        for item in preview["skus"]:
            valid_quotes = [
                quote
                for quote in item["supplier_quotes"]
                if quote["supplier_id"] is not None
            ]
            writer.writerow(
                {
                    "sku_group_id": item["sku_group_id"],
                    "sku_code": item["sku_code"],
                    "canonical_spu_id": item["canonical_spu_id"],
                    "canonical_parts_id": item["canonical_parts_id"],
                    "representative_parts_id": item["representative_parts_id"],
                    "nature": item["nature"],
                    "retail_price": item["retail_price"] or "",
                    "source_parts_ids": ",".join(
                        str(value) for value in item["source_parts_ids"]
                    ),
                    "source_spu_ids": ",".join(
                        str(value) for value in item["source_spu_ids"]
                    ),
                    "supplier_count": len(valid_quotes),
                    "suppliers": "；".join(
                        quote["supplier_name"] for quote in valid_quotes
                    ),
                    "status": (
                        "待配置价格"
                        if item["retail_price"] is None
                        else "可迁移"
                    ),
                }
            )


def main() -> int:
    args = parse_args()
    source_path = args.source_sql.expanduser().resolve()
    state_path = args.spu_state.expanduser().resolve()
    source_hash = source_file_sha256(source_path)
    rows = list(source_rows_from_sql(source_path, 1, None, None, None))
    state = load_spu_state(state_path, source_path, source_hash)
    preview = build_preview(rows, state, source_path, source_hash)
    write_json_atomic(args.json_output.resolve(), preview)
    write_csv(args.csv_output.resolve(), preview)

    summary = preview["summary"]
    print(
        "[SKU预检完成] "
        f"parts={summary['source_parts']}，"
        f"规范SPU={summary['spu_groups']}，"
        f"SKU={summary['sku_groups']}，"
        f"合并来源行={summary['merged_source_rows']}，"
        f"多供应商SKU={summary['multi_supplier_skus']}，"
        f"来源覆盖={summary['source_coverage']}"
    )
    print(f"JSON：{args.json_output.resolve()}")
    print(f"CSV：{args.csv_output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
