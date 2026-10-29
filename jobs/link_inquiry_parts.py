#!/usr/bin/env python
"""方案第 0 步：OA 已完成询价按规格型号匹配 parts，只读输出分类明细。

不建表、不写任何数据。跑完看终端分类统计和 jobs/inquiry_link_preview.csv，
确认口径后再做建表与自动写入（第 1、2 步）。

用法：
    python jobs/link_inquiry_parts.py
    python jobs/link_inquiry_parts.py --limit 20

分类口径见 docs 里的《询价记录与产品库（SPU）关联方案》。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from jobs._prod_db import describe, oa_conn, prod_conn  # noqa: E402

OUT_PATH = PROJECT_DIR / "jobs" / "inquiry_link_preview.csv"

# 空格、换行、逗号、顿号、分号、竖线切分。
# 斜杠不切：WECO-957L/GCE、GYFB-809B/1035B 这类斜杠属于型号本身，切了就永远匹配不上。
_SPLIT_RE = re.compile(r"[\s,，、;；|]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ALPHA_RE = re.compile(r"[A-Z]")

MATCH_LABELS = {
    1: "型号唯一",
    2: "多条对多条",
    3: "规格为空或纯尺寸",
    4: "人工关联",
    5: "尺寸/品类名对不上",
    6: "型号但库中没有",
    7: "描述文字",
    9: "人工忽略",
}

INQUIRY_SQL = """
    SELECT m.id AS mission_id, m.order_goods_id, g.goods_spec, g.goods_name, g.factory
    FROM yh_query_goods_mission m
    JOIN yh_query_order_goods g ON g.id = m.order_goods_id
    WHERE m.mission_type = 1 AND m.mission_status = 4
      AND (m.delete_time IS NULL OR YEAR(m.delete_time) = 0)
    ORDER BY m.id
"""


def normalize(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().upper()


def split_tokens(value) -> list[str]:
    return [
        re.sub(r"\s+", "", token)
        for token in _SPLIT_RE.split(normalize(value))
        if token.strip()
    ]


def slash_variants(token: str) -> list[str]:
    """整串没命中时，才把斜杠两侧拆开再试一次。"""
    if "/" not in token:
        return []
    return [part for part in token.split("/") if len(part) >= 4]


def is_dimension(token: str) -> bool:
    """纯尺寸或结构参数，如 400*5*10、540*7*10-60*208-15-125。

    这类值跨品类通用（曳引轮、导向轮、轿顶轮都可能一样），不能当型号关联。
    """
    return "*" in token and bool(re.fullmatch(r"[\d.,\-*xX×]+", token))


def looks_like_model(token: str) -> bool:
    """带英文字母的才可能是型号；纯数字、纯尺寸、纯中文都不算。"""
    return len(token) >= 4 and bool(_ALPHA_RE.search(token))


def build_index(parts: list[dict]) -> dict[str, set[int]]:
    index: dict[str, set[int]] = defaultdict(set)
    for row in parts:
        part_id = int(row["id"])
        for field in ("model", "substitute_model"):
            for token in split_tokens(row.get(field)):
                index[token].add(part_id)
    return index


def classify(spec, index: dict[str, set[int]]) -> tuple[int, str, list[int]]:
    """返回 (match_type, 命中的型号 token, 候选 part_id 列表)。"""
    tokens = split_tokens(spec)
    if not tokens:
        return 3, "", []
    if any(is_dimension(token) for token in tokens):
        return 3, "", []

    usable = [t for t in tokens if len(t) >= 4 and not t.isdigit()]
    hits: set[int] = set()
    matched = ""
    for token in usable:
        found = set(index.get(token) or ())
        used_key = token
        if not found:
            for sub in slash_variants(token):
                sub_hit = index.get(sub) or set()
                if sub_hit:
                    found = sub_hit
                    used_key = sub
                    break
        if found:
            hits |= found
            matched = matched or used_key

    if len(hits) == 1:
        return 1, matched, sorted(hits)
    if len(hits) > 1:
        return 2, matched, sorted(hits)
    if _CJK_RE.search("".join(tokens)):
        # 短中文多是品类名（第5类），长句才算描述文字（第7类）。阈值可调。
        return (5 if len("".join(tokens)) <= 6 else 7), "", []
    # 没命中且不像型号（纯数字、电气参数里的数字串），归到规格对不上
    return (6 if any(looks_like_model(t) for t in tokens) else 5), "", []


def fetch_parts() -> list[dict]:
    conn = prod_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, model, substitute_model, product_name FROM parts")
            return list(cur.fetchall())
    finally:
        conn.close()


def fetch_inquiries(limit: int | None) -> list[dict]:
    sql = INQUIRY_SQL + (" LIMIT %s" if limit else "")
    conn = oa_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,) if limit else ())
            return list(cur.fetchall())
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="OA 询价与 parts 型号匹配的只读分类统计")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 条询价")
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    print("产品库:", describe())
    parts = fetch_parts()
    index = build_index(parts)
    print("parts 条数:", len(parts), "| 型号 token 数:", len(index))

    inquiries = fetch_inquiries(args.limit)
    print("询价条数:", len(inquiries))

    counter: Counter[int] = Counter()
    unit_keys: dict[int, set[str]] = defaultdict(set)
    rows: list[dict] = []
    for item in inquiries:
        spec = item.get("goods_spec") or ""
        match_type, matched_key, candidates = classify(spec, index)
        counter[match_type] += 1
        unit_keys[match_type].add(normalize(spec) or f"#{item['mission_id']}")
        rows.append(
            {
                "match_type": match_type,
                "part_id": candidates[0] if match_type == 1 else "",
                "candidates": ",".join(str(c) for c in candidates),
                "matched_key": matched_key,
                "goods_spec": spec,
                "goods_name": item.get("goods_name") or "",
                "factory": item.get("factory") or "",
                "inquiry_mission_id": item["mission_id"],
                "order_goods_id": item.get("order_goods_id") or "",
            }
        )

    total = len(rows) or 1
    print()
    print("%-4s %-18s %6s %8s %10s" % ("类型", "说明", "条数", "占比", "去重单位"))
    for match_type in sorted(counter):
        count = counter[match_type]
        print(
            "%-4s %-18s %6d %7.1f%% %10d"
            % (
                match_type,
                MATCH_LABELS.get(match_type, "未知"),
                count,
                count * 100.0 / total,
                len(unit_keys[match_type]),
            )
        )
    auto = counter[1]
    print()
    print("型号唯一命中: %d 条，占 %.1f%%（仅供参考，不写库）" % (auto, auto * 100.0 / total))

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    print("明细已写入:", output)
    return 0


def _self_check() -> None:
    index = {
        "WECO-957L/GCE": {1},
        "LRS-150-24": {2, 3},
        "BS34C": {4},
    }
    assert normalize(" 16B-2  102节 ") == "16B-2 102节"
    assert split_tokens("ELE-420D-50，HAA621BX2") == ["ELE-420D-50", "HAA621BX2"]
    assert classify("WECO-957L/GCE", index)[0] == 1
    assert classify("LRS-150-24", index)[0] == 2
    assert classify("", index)[0] == 3
    assert classify("450*5*10", index)[0] == 3
    assert classify("540*7*10-60*208-15-125", index)[0] == 3
    assert classify("10", index)[0] == 5
    assert classify("双开关", index)[0] == 5
    assert classify("康力专用操作器，匹配如图的主板", index)[0] == 7
    assert classify("NOT-A-REAL-MODEL", index)[0] == 6
    print("self-check 通过")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        sys.exit(main())
