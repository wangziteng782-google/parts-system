#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""查询：不含税单价未填写，但含税单价有值且对应税率0%的记录"""

import pymysql


def main():
    parts_conn = pymysql.connect(
        host='120.46.152.222', port=3306,
        user='parts_database', password='1234',
        database='parts_database', charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )
    oa_conn = pymysql.connect(
        host='120.46.152.222', port=3306,
        user='oa_yixiuti', password='npFKTmTpzTzGAEcr',
        database='oa_yixiuti', charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )

    # 1. 从 OA 库获取税率0%的供应商
    oa_tax_zero = {}
    with oa_conn.cursor() as cur:
        cur.execute("""SELECT s.supplier_name,
                              d.is_special_invoice, d.special_tax_point,
                              d.is_normal_invoice, d.normal_tax_point
                       FROM yh_supplier s
                       INNER JOIN yh_supplier_detail d ON d.supplier_id = s.id AND d.delete_time IS NULL
                       WHERE s.delete_time IS NULL
                         AND ((d.is_special_invoice = 1 AND d.special_tax_point = 0)
                              OR (d.is_normal_invoice = 1 AND d.normal_tax_point = 0))""")
        for row in cur.fetchall():
            name = row['supplier_name']
            if name not in oa_tax_zero:
                oa_tax_zero[name] = {'special_tax_zero': False, 'normal_tax_zero': False}
            if row['is_special_invoice'] and row['special_tax_point'] == 0:
                oa_tax_zero[name]['special_tax_zero'] = True
            if row['is_normal_invoice'] and row['normal_tax_point'] == 0:
                oa_tax_zero[name]['normal_tax_zero'] = True

    # 2. 从 parts 库查不含税价为空但有含税价的记录
    with parts_conn.cursor() as cur:
        cur.execute("""SELECT vpp.id, vpp.part_id, vpp.supplier,
                              vpp.no_tax_price, vpp.purchase_special_invoice, vpp.purchase_general_invoice,
                              p.model, p.product_name
                       FROM product_variant_prices vpp
                       LEFT JOIN parts p ON p.id = vpp.part_id
                       WHERE (vpp.no_tax_price IS NULL OR vpp.no_tax_price = 0)
                         AND (vpp.purchase_special_invoice IS NOT NULL AND vpp.purchase_special_invoice != 0
                              OR vpp.purchase_general_invoice IS NOT NULL AND vpp.purchase_general_invoice != 0)""")
        records = cur.fetchall()

    # 3. 匹配输出
    results = []
    for r in records:
        supplier = r['supplier']
        if supplier in oa_tax_zero:
            info = oa_tax_zero[supplier]
            if (r['purchase_special_invoice'] and r['purchase_special_invoice'] != 0 and info['special_tax_zero']) or \
               (r['purchase_general_invoice'] and r['purchase_general_invoice'] != 0 and info['normal_tax_zero']):
                results.append(r)

    print(f"找到 {len(results)} 条记录：")
    for r in results:
        print(f"  id={r['id']}, 型号={r['model']}, 名称={r['product_name']}, "
              f"供应商={r['supplier']}, 不含税={r['no_tax_price']}, "
              f"专票={r['purchase_special_invoice']}, 普票={r['purchase_general_invoice']}")

    parts_conn.close()
    oa_conn.close()


if __name__ == "__main__":
    main()
