"""SPU 关联方案第 0 步：只读统计产品库与 OA 询价的规模。

必须跑在服务器上（连的是 .env 里配置的正式库），不要在本地跑，本地是旧副本。
只做 SELECT，不写任何数据。

用法：
    cd /www/wwwroot/parts-system-test
    .venv/bin/python jobs/_stats_spu_link.py
"""

import sys

import pymysql

from parts_system.config.constants import DB_CONFIG, OA_DB_CONFIG

sys.stdout.reconfigure(encoding="utf-8")


def fetch_one(cur, sql):
    cur.execute(sql)
    return cur.fetchone()


def main():
    parts = pymysql.connect(**DB_CONFIG)
    oa = pymysql.connect(**OA_DB_CONFIG)
    pc, oc = parts.cursor(), oa.cursor()

    try:
        print("=" * 56)
        print("产品库 %s@%s/%s" % (DB_CONFIG["user"], DB_CONFIG["host"], DB_CONFIG["database"]))
        print("=" * 56)
        print("parts 总条数        :", fetch_one(pc, "SELECT COUNT(*) c FROM parts")["c"])
        print("model 非空          :", fetch_one(pc, "SELECT COUNT(*) c FROM parts WHERE model IS NOT NULL AND model<>''")["c"])
        print("substitute_model 非空:", fetch_one(pc, "SELECT COUNT(*) c FROM parts WHERE substitute_model IS NOT NULL AND substitute_model<>''")["c"])
        print("product_name 去重   :", fetch_one(pc, "SELECT COUNT(DISTINCT product_name) c FROM parts")["c"])
        print("model 重复组数      :", fetch_one(pc, "SELECT COUNT(*) c FROM (SELECT model FROM parts WHERE model<>'' GROUP BY model HAVING COUNT(*)>1) t")["c"])
        print("model 重复涉及条数  :", fetch_one(pc, """
            SELECT COALESCE(SUM(n),0) s FROM (
                SELECT COUNT(*) n FROM parts WHERE model<>'' GROUP BY model HAVING COUNT(*)>1
            ) t
        """)["s"])
        pc.execute("SHOW TABLES LIKE 'part_inquiries'")
        print("part_inquiries 已存在:", bool(pc.fetchall()))

        print()
        print("=" * 56)
        print("OA 库 %s@%s/%s" % (OA_DB_CONFIG["user"], OA_DB_CONFIG["host"], OA_DB_CONFIG["database"]))
        print("=" * 56)
        base = """
            FROM yh_query_goods_mission m
            LEFT JOIN yh_query_order_goods g ON g.id = m.order_goods_id
            WHERE m.mission_type=1 AND m.mission_status=4
              AND (m.delete_time IS NULL OR m.delete_time='' OR m.delete_time='0000-00-00 00:00:00')
        """
        print("已完成询价          :", fetch_one(oc, "SELECT COUNT(*) c " + base)["c"])
        print("ele_type 非空       :", fetch_one(oc, "SELECT COUNT(*) c " + base + " AND g.ele_type IS NOT NULL AND g.ele_type<>''")["c"])
        print("goods_spec 非空     :", fetch_one(oc, "SELECT COUNT(*) c " + base + " AND g.goods_spec IS NOT NULL AND g.goods_spec<>''")["c"])
        print("goods_spec 为空     :", fetch_one(oc, "SELECT COUNT(*) c " + base + " AND (g.goods_spec IS NULL OR g.goods_spec='')")["c"])
        print("goods_spec 去重值   :", fetch_one(oc, "SELECT COUNT(DISTINCT g.goods_spec) c " + base + " AND g.goods_spec<>''")["c"])
    finally:
        parts.close()
        oa.close()


if __name__ == "__main__":
    main()
