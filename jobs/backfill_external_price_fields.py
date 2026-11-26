"""商品库商品（定价模式 2）销售价的对外展示类型回填。

规则严格按业务给的存量品类口径：
1. 钢丝绳类、断电平层类、钢带类、补偿链类、接触器/继电器类 → 含专票(special)
2. 空调类：菱润含税则含专票，不含税则不含票；其他供应商 → 含专票
3. 光幕类：佳格、皓睿机电 → 含专票；其余 → 不含票
4. 梯控类：只奥盟 → 含专票；其余 → 不含票
5. 风扇类/风幕机类：风幕机 → 含专票；风扇 → 不含票
6. 表内未列出的品类不写入（保留原值），脚本会打印出来待补

用法：
    python jobs/backfill_external_price_fields.py           # 只预览
    python jobs/backfill_external_price_fields.py --apply   # 实际写入
"""
import argparse
import os
import sys
from collections import Counter, defaultdict

import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parts_system.config.constants import DB_CONFIG  # noqa: E402

TIER_CONTROL_WORDS = ("梯控", "控制器", "读卡器", "人脸", "发卡器", "加密器", "读头")
LINGRUN_WORDS = ("菱润", "凌润")


def decide(product_name: str, suppliers: str, invoice_company: str):
    """返回 no_tax / special / general；表内未列出的品类返回 None（不写入）。"""
    name = product_name or ""
    suppliers = suppliers or ""
    invoice = invoice_company or ""

    # 风扇类/风幕机类
    if "风幕" in name:
        return "special"
    if "风扇" in name:
        return "no_tax"
    # 钢丝绳类
    if "钢丝绳" in name:
        return "special"
    # 断电平层类
    if "断电" in name:
        return "special"
    # 钢带类
    if "钢带" in name:
        return "special"
    # 补偿链类
    if "补偿链" in name:
        return "special"
    # 接触器/继电器类
    if "接触器" in name or "继电器" in name:
        return "special"
    # 空调类：菱润有含税有不含税，其余供应商含专（商品名多为 1P/1.5P 单冷、冷暖）
    if "空调" in name or "单冷" in name or "冷暖" in name:
        if any(word in suppliers for word in LINGRUN_WORDS):
            return "special" if "专" in invoice else "no_tax"
        return "special"
    # 光幕类：佳格、皓睿机电含专，其余不含
    if "光幕" in name:
        if "佳格" in suppliers or "皓睿" in suppliers:
            return "special"
        return "no_tax"
    # 梯控类：只奥盟含专，其余不含
    if any(word in name for word in TIER_CONTROL_WORDS):
        return "special" if "奥盟" in suppliers else "no_tax"
    return None


def fetch_rows(cur):
    cur.execute(
        """SELECT p.id AS part_id, p.product_name, p.product_type,
                  v.id AS price_id, v.variant_group_id, v.retail_price,
                  v.retail_invoice_company,
                  (SELECT GROUP_CONCAT(DISTINCT v2.supplier)
                     FROM product_variant_prices v2
                    WHERE v2.part_id=p.id AND v2.supplier<>'') AS suppliers
             FROM product_variant_prices v
             JOIN parts p ON p.id=v.part_id
            WHERE p.pricing_mode=2 AND v.supplier=''
            ORDER BY p.id, v.id"""
    )
    return cur.fetchall()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际写入数据库")
    args = parser.parse_args()

    conn = pymysql.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        rows = fetch_rows(cur)
        planned = []
        skipped = []
        for row in rows:
            if row.get("retail_price") is None:
                continue
            target = decide(row["product_name"], row.get("suppliers"), row.get("retail_invoice_company"))
            if target is None:
                skipped.append(row)
                continue
            planned.append((row, target))

        by_field = Counter(target for _, target in planned)
        by_type = defaultdict(Counter)
        changed = 0
        for row, target in planned:
            by_type[row.get("product_type") or "(空)"][target] += 1
            cur.execute(
                "SELECT external_price_fields FROM product_variant_prices WHERE id=%s",
                (row["price_id"],),
            )
            current = (cur.fetchone() or {}).get("external_price_fields") or ""
            if current != target:
                changed += 1

        print(f"销售价行总数：{len(rows)}，按表可写：{len(planned)}，需要变更：{changed}")
        print("按对外展示类型：", dict(by_field))
        print("\n按产品分类：")
        for ptype, counter in sorted(by_type.items(), key=lambda kv: -sum(kv[1].values())):
            print(f"  {ptype}: {dict(counter)}")

        print("\n抽样 15 条：")
        for row, target in planned[:15]:
            print(f"  [{target}] {row['product_name']} | {row.get('retail_invoice_company')} | {row.get('suppliers')}")

        if skipped:
            skip_by_name = Counter(r["product_name"] for r in skipped)
            print(f"\n表内未列出的品类（不写入，共 {len(skipped)} 行 / {len(skip_by_name)} 个商品）：")
            for name, count in skip_by_name.most_common(40):
                print(f"  {count:>3} 行  {name}")

        if not args.apply:
            print("\n预览模式，未写入。确认后加 --apply 执行。")
            return

        # 写入前留一份原值，便于回滚
        cur.execute(
            "CREATE TABLE IF NOT EXISTS product_variant_prices_ext_fields_bak "
            "AS SELECT id, external_price_fields FROM product_variant_prices"
        )
        for row, target in planned:
            cur.execute(
                "UPDATE product_variant_prices SET external_price_fields=%s WHERE id=%s",
                (target, row["price_id"]),
            )
        # 同步重算商品库商品的对外展示价区间（只统计选了对外展示类型的销售价行）
        cur.execute(
            """UPDATE parts p
                 JOIN (SELECT part_id, MIN(retail_price) AS mn, MAX(retail_price) AS mx
                         FROM product_variant_prices
                        WHERE supplier=''
                          AND external_price_fields IS NOT NULL AND external_price_fields<>''
                        GROUP BY part_id) t ON t.part_id=p.id
                  SET p.display_price_min=t.mn, p.display_price_max=t.mx
                WHERE p.pricing_mode=2"""
        )
        cur.execute(
            """UPDATE parts p
                 SET p.display_price_min=NULL, p.display_price_max=NULL
               WHERE p.pricing_mode=2
                 AND NOT EXISTS (SELECT 1 FROM product_variant_prices v
                                  WHERE v.part_id=p.id AND v.supplier=''
                                    AND v.external_price_fields IS NOT NULL
                                    AND v.external_price_fields<>'')"""
        )
        conn.commit()
        print(f"\n已写入 {len(planned)} 条销售价行的对外展示类型，并重算展示价区间。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
