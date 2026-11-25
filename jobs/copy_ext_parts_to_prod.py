"""把测试库里 OA 导入的商品（sku_code 以 EXT- 开头）连同规格、报价复制到正式库。

用法：
    python -m jobs.copy_ext_parts_to_prod --dry-run
    python -m jobs.copy_ext_parts_to_prod
    python -m jobs.copy_ext_parts_to_prod --limit 20

幂等：正式库已有同 sku_code 的 part 直接跳过，不会重复插入。
"""
import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymysql

from parts_system.config.constants import DB_CONFIG
from parts_system.inquiry_sync import PROD_DB

MAP_OUT = ROOT / "tmp" / "ext_part_map.csv"
TABLES = ("product_variant_specs", "product_variant_group_specs", "product_variant_prices")
BATCH = 20


def connect(config):
    c = dict(config)
    c["charset"] = "utf8mb4"
    c["cursorclass"] = pymysql.cursors.DictCursor
    c.setdefault("connect_timeout", 15)
    return pymysql.connect(**c)


def columns(cur, table):
    cur.execute(f"SHOW COLUMNS FROM `{table}`")
    return [r["Field"] for r in cur.fetchall()]


def insert_sql(table, cols):
    col_sql = ", ".join(f"`{c}`" for c in cols)
    marks = ", ".join(["%s"] * len(cols))
    return f"INSERT INTO `{table}` ({col_sql}) VALUES ({marks})"


def copy_part(src_cur, dst_cur, part, dry_run):
    """复制一个 SPU 及其 SKU，返回 (新 part_id, 规格数, 组合数, 报价数)。"""
    old_id = part["id"]
    part_cols = [c for c in part if c != "id"]
    values = [part[c] for c in part_cols]

    if dry_run:
        new_id = None
    else:
        dst_cur.execute(insert_sql("parts", part_cols), values)
        new_id = dst_cur.lastrowid

    # 规格字典：老 id → 新 id
    src_cur.execute("SELECT * FROM product_variant_specs WHERE part_id=%s ORDER BY id", (old_id,))
    specs = src_cur.fetchall()
    spec_map = {}
    for spec in specs:
        cols = [c for c in spec if c != "id"]
        row = [new_id if c == "part_id" else spec[c] for c in cols]
        if dry_run:
            spec_map[spec["id"]] = None
            continue
        dst_cur.execute(insert_sql("product_variant_specs", cols), row)
        spec_map[spec["id"]] = dst_cur.lastrowid

    # 规格组合
    src_cur.execute("SELECT * FROM product_variant_group_specs WHERE part_id=%s ORDER BY id", (old_id,))
    groups = src_cur.fetchall()
    for grp in groups:
        cols = [c for c in grp if c != "id"]
        row = []
        for c in cols:
            if c == "part_id":
                row.append(new_id)
            elif c == "spec_id":
                row.append(spec_map.get(grp["spec_id"]))
            else:
                row.append(grp[c])
        if not dry_run:
            dst_cur.execute(insert_sql("product_variant_group_specs", cols), row)

    # 价格行
    src_cur.execute("SELECT * FROM product_variant_prices WHERE part_id=%s ORDER BY id", (old_id,))
    prices = src_cur.fetchall()
    for price in prices:
        cols = [c for c in price if c != "id"]
        row = [new_id if c == "part_id" else price[c] for c in cols]
        if not dry_run:
            dst_cur.execute(insert_sql("product_variant_prices", cols), row)

    return new_id, len(specs), len(groups), len(prices)


def main():
    parser = argparse.ArgumentParser(description="复制 EXT- 商品到正式库")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0, help="跳过前 N 条，分批跑用")
    args = parser.parse_args()

    src = connect(DB_CONFIG)
    dst = connect(PROD_DB)
    sc, dc = src.cursor(), dst.cursor()

    src_parts_cols = columns(sc, "parts")
    dst_parts_cols = columns(dc, "parts")
    missing = [c for c in src_parts_cols if c not in dst_parts_cols]
    if missing:
        print(f"正式库 parts 缺少字段：{missing}，请先补列再导入")
        return 1

    print(f"源库   {DB_CONFIG['host']}/{DB_CONFIG['database']}")
    print(f"正式库 {PROD_DB['host']}/{PROD_DB['database']}")
    print(f"模式   {'dry-run' if args.dry_run else '写库'}")

    sc.execute("SELECT * FROM parts WHERE sku_code LIKE 'EXT-%%' ORDER BY id")
    parts = sc.fetchall()[args.offset:]
    if args.limit:
        parts = parts[: args.limit]

    dc.execute("SELECT sku_code FROM parts WHERE sku_code LIKE 'EXT-%%'")
    existing = {r["sku_code"] for r in dc.fetchall()}

    ok = skip = fail = 0
    spec_total = group_total = price_total = 0
    mapping = []

    try:
        for index, part in enumerate(parts, start=1):
            code = part["sku_code"]
            if code in existing:
                skip += 1
                print(f"  [{index}/{len(parts)}] {code} 正式库已存在，跳过")
                continue
            try:
                new_id, s, g, p = copy_part(sc, dc, part, args.dry_run)
                if not args.dry_run:
                    dst.commit()
                ok += 1
                spec_total += s
                group_total += g
                price_total += p
                mapping.append([part["id"], new_id if new_id else "", code, part["model"], part["product_name"], s, g, p])
                if index % BATCH == 0 or index == len(parts):
                    print(f"  [{index}/{len(parts)}] 已处理 {ok} 条（最新 {code} → {'(dry)' if args.dry_run else new_id}）")
            except Exception as exc:
                if not args.dry_run:
                    dst.rollback()
                fail += 1
                print(f"  [{index}/{len(parts)}] {code} 失败: {type(exc).__name__}: {exc}")
    finally:
        sc.close()
        src.close()
        dc.close()
        dst.close()

    if mapping:
        MAP_OUT.parent.mkdir(exist_ok=True)
        new_file = not MAP_OUT.exists()
        with MAP_OUT.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["src_part_id", "new_part_id", "sku_code", "model", "name",
                            "specs", "groups", "prices"])
            w.writerows(mapping)
        print(f"\n导入映射：{MAP_OUT}")

    print(f"\n结果：成功 {ok}，跳过 {skip}，失败 {fail}")
    print(f"规格 {spec_total}，组合 {group_total}，报价 {price_total}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
