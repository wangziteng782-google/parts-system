"""Write a small set of clearly labelled records for previewing the log page."""

from datetime import datetime, timedelta
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from parts_system.shared import ensure_employee_operation_logs_table, get_db


DEMO_MARKER = "【页面演示数据】"


def main():
    now = datetime.now().replace(microsecond=0)
    rows = [
        (
            22,
            1,
            "UPDATE",
            "PRODUCT",
            f"{DEMO_MARKER}修改产品型号：NSFC01 → NSFC01-01A",
            now - timedelta(minutes=4),
        ),
        (
            33,
            2,
            "CREATE",
            "PRODUCT",
            f"{DEMO_MARKER}新增配件“指令板”，并补充品牌与产品分类",
            now - timedelta(minutes=12),
        ),
        (
            87,
            3,
            "UPDATE",
            "SPEC",
            f"{DEMO_MARKER}为显示板配置规格：性质、显示、协议、颜色",
            now - timedelta(minutes=28),
        ),
        (
            89,
            4,
            "UPDATE",
            "PRICE",
            f"{DEMO_MARKER}修改供应商报价：采购成本价调整为680元",
            now - timedelta(hours=1, minutes=6),
        ),
        (
            22,
            5,
            "UPDATE",
            "IMAGE",
            f"{DEMO_MARKER}更新关键部位图片和实物图照片",
            now - timedelta(hours=2, minutes=18),
        ),
        (
            33,
            6,
            "DELETE",
            "SPEC",
            f"{DEMO_MARKER}删除未使用的规格组合：颜色=蓝色",
            now - timedelta(hours=3, minutes=35),
        ),
        (
            87,
            1,
            "UPDATE",
            "CLASSIFICATION",
            f"{DEMO_MARKER}产品分类调整为门机控制器",
            now - timedelta(days=1, minutes=20),
        ),
        (
            89,
            2,
            "DELETE",
            "PRODUCT",
            f"{DEMO_MARKER}删除一条确认重复的配件记录",
            now - timedelta(days=1, hours=2),
        ),
    ]

    conn = get_db()
    try:
        ensure_employee_operation_logs_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM employee_operation_logs WHERE detail LIKE %s",
            (f"{DEMO_MARKER}%",),
        )
        cursor.executemany(
            """
            INSERT INTO employee_operation_logs
                (user_id, part_id, operation_type, module_code, detail, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            rows,
        )
        conn.commit()
        print(f"已写入 {cursor.rowcount} 条日志页面演示数据")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
