"""只回填商品库（EXT-）商品的「质保」和「技术参数」两个字段，不重导数据。

从 OA 爆品取数，按与导入脚本一致的口径（同型号分组取最新一条）比对后更新：
    - parts.warranty: warranty_month 0 → 无质保，其余 → X个月
    - parts.technical_params: 安装尺寸
    - product_variant_prices.warranty_time: 与该商品质保保持一致（sales 详情优先读这里）

用法：
    python -m jobs.backfill_external_extra_fields --env test            # 只看差异
    python -m jobs.backfill_external_extra_fields --env test --yes      # 写入
    python -m jobs.backfill_external_extra_fields --env prod --yes
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

from jobs._prod_db import describe, prod_config
from jobs.import_external_goods import (
    _build_technical_params,
    _warranty_text,
    load_from_oa,
)
from parts_system.config.constants import DB_CONFIG


def connect(env: str):
    config = dict(prod_config()) if env == "prod" else dict(DB_CONFIG)
    config["charset"] = "utf8mb4"
    config["cursorclass"] = pymysql.cursors.DictCursor
    config.setdefault("connect_timeout", 10)
    return pymysql.connect(**config)


def build_tasks(items):
    """与导入脚本一致：有型号按型号聚合成 SPU，无型号每条单独一个 SPU。"""
    groups = {}
    singles = []
    for item in items:
        spec = str(item.get("goods_spec") or "").strip()
        if spec:
            groups.setdefault(spec, []).append(item)
        else:
            singles.append([item])
    return list(groups.values()) + singles


def main():
    parser = argparse.ArgumentParser(description="回填商品库商品的质保与技术参数")
    parser.add_argument("--env", choices=("test", "prod"), default="test")
    parser.add_argument("--yes", action="store_true", help="确认写入")
    args = parser.parse_args()

    items = load_from_oa(None, 2)
    tasks = build_tasks(items)
    print(f"OA 爆品 {len(items)} 条，聚合后 SPU {len(tasks)} 个")
    print(f"目标库: {describe() if args.env == 'prod' else DB_CONFIG['host'] + '/' + DB_CONFIG['database']}")
    print(f"模式: {'写库' if args.yes else '只看差异'}")

    conn = connect(args.env)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, sku_code, model, warranty, technical_params"
            " FROM parts WHERE sku_code LIKE 'EXT-%'"
        )
        local = {row["sku_code"]: row for row in cur.fetchall()}
        print(f"本地商品库 {len(local)} 条")

        changed, unchanged, missing = 0, 0, 0
        price_changed = 0
        samples = []
        for rows in tasks:
            first = rows[0]
            min_id = min(int(row.get("id") or 0) for row in rows)
            sku_code = f"EXT-{min_id}"
            row = local.get(sku_code)
            if not row:
                missing += 1
                continue

            new_warranty = _warranty_text(first.get("warranty_month")) or None
            new_params = _build_technical_params(first) or None
            old_warranty = row.get("warranty")
            old_params = row.get("technical_params")
            parts_dirty = old_warranty != new_warranty or old_params != new_params

            if parts_dirty:
                changed += 1
                if len(samples) < 8:
                    samples.append((row["id"], sku_code, row.get("model"),
                                    old_warranty, new_warranty, old_params, new_params))
            else:
                unchanged += 1

            if args.yes:
                if parts_dirty:
                    cur.execute(
                        "UPDATE parts SET warranty=%s, technical_params=%s WHERE id=%s",
                        (new_warranty, new_params, row["id"]),
                    )
                # 报价行的质保优先级高于商品级，sales 详情会先读这里，保持两处一致
                cur.execute(
                    "UPDATE product_variant_prices SET warranty_time=%s"
                    " WHERE part_id=%s AND COALESCE(warranty_time, '') <> %s",
                    (new_warranty, row["id"], new_warranty or ""),
                )
                price_changed += cur.rowcount
            else:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM product_variant_prices"
                    " WHERE part_id=%s AND COALESCE(warranty_time, '') <> %s",
                    (row["id"], new_warranty or ""),
                )
                price_changed += cur.fetchone()["c"]

        if args.yes:
            conn.commit()

        print(f"待更新商品 {changed} 条，无变化 {unchanged} 条，未匹配 {missing} 条，报价行 {price_changed} 行")
        for item in samples:
            print("  样例: id=%s sku=%s 型号=%s | 质保 %r → %r | 技术参数 %r → %r" % item)
        if not args.yes:
            print("\n未写入，确认后加 --yes 执行")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
