"""项目配置常量：数据库、七牛云、分类树、字段映射等。"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# ========== 路径 ==========
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")

# ========== 日志配置 ==========
logger = logging.getLogger("parts_system")
logger.setLevel(logging.DEBUG)
logger.handlers.clear()
logger.propagate = False

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.DEBUG)
_console_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logger.addHandler(_console_handler)

logger.info("=" * 60)
logger.info("电梯配件管理系统启动 | 日志输出方式=仅控制台 | 级别=DEBUG")
logger.info("=" * 60)

# ========== 主数据库配置 ==========
import pymysql

DB_CONFIG = {
    "host": os.getenv("PARTS_DB_HOST", "localhost").strip(),
    "port": int(os.getenv("PARTS_DB_PORT", "3306")),
    "user": os.getenv("PARTS_DB_USER", "root").strip(),
    "password": os.getenv("PARTS_DB_PASSWORD", "1234"),
    "database": os.getenv("PARTS_DB_NAME", "parts_database").strip(),
    "charset": os.getenv("PARTS_DB_CHARSET", "utf8mb4").strip(),
    "cursorclass": pymysql.cursors.DictCursor,
    "connect_timeout": int(os.getenv("PARTS_DB_CONNECT_TIMEOUT", "10")),
}

# ========== OA 数据库配置 ==========
OA_DB_CONFIG = {
    "host": os.getenv("OA_DB_HOST", "localhost").strip(),
    "port": int(os.getenv("OA_DB_PORT", "3306")),
    "user": os.getenv("OA_DB_USER", "root").strip(),
    "password": os.getenv("OA_DB_PASSWORD", ""),
    "database": os.getenv("OA_DB_NAME", "oa_yixiuti").strip(),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "connect_timeout": int(os.getenv("OA_DB_CONNECT_TIMEOUT", "5")),
    "read_timeout": int(os.getenv("OA_DB_READ_TIMEOUT", "12")),
}

# ========== 七牛云配置 ==========
_QINIU_LOCAL_FILE = LOG_DIR / "qiniu_config.local.json"


def _load_qiniu_local() -> dict:
    if not _QINIU_LOCAL_FILE.exists():
        return {}
    try:
        with open(_QINIU_LOCAL_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception as e:
        logger.warning(f"[七牛配置] 本地配置文件读取失败 | error={e}")
        return {}


_qiniu_local = _load_qiniu_local()

QINIU_CONFIG = {
    "access_key": os.getenv("QINIU_ACCESS_KEY", "").strip() or str(_qiniu_local.get("access_key", "")).strip(),
    "secret_key": os.getenv("QINIU_SECRET_KEY", "").strip() or str(_qiniu_local.get("secret_key", "")).strip(),
    "bucket": os.getenv("QINIU_BUCKET", "").strip() or str(_qiniu_local.get("bucket", "")).strip(),
    "domain": (
        os.getenv("QINIU_DOMAIN", "").strip()
        or str(_qiniu_local.get("domain", "")).strip()
    ).rstrip("/"),
}

# ========== 图片上传 ==========
MAX_UPLOAD_IMAGE_SIZE = 10 * 1024 * 1024
MAX_UPLOAD_IMAGE_COUNT = 20
ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}

# ========== 产品分类树 ==========
PRODUCT_CLASSIFICATION_TREE = [
    {
        "name": "机房部件",
        "children": [
            {"name": "控制柜类", "children": ["主板", "驱动板", "变频器", "机房话机", "制动电阻", "开关电源", "一体机", "变频器风扇", "接触器", "相序继电器", "松闸电源"]},
            {"name": "曳引机类", "children": ["曳引机", "编码器", "制动器", "曳引轮"]},
            {"name": "限速器类", "children": ["限速器", "限速器开关"]},
        ],
    },
    {
        "name": "轿厢部件",
        "children": [
            {"name": "操纵盘类", "children": ["轿厢显示板", "指令板", "轿厢通讯板", "按钮"]},
            {"name": "轿顶检修箱类", "children": ["轿顶板", "应急电池", "检修按钮"]},
            {"name": "平层感应器类", "children": ["平层感应器", "平层开关"]},
            {"name": "反绳轮类", "children": ["反绳轮"]},
            {"name": "光幕类", "children": ["光幕"]},
        ],
    },
    {
        "name": "井道部件",
        "children": [
            {"name": "井道灯类", "children": ["井道灯"]},
            {"name": "钢丝绳类", "children": ["钢丝绳", "钢丝绳绳头"]},
            {"name": "导轨类", "children": ["导轨", "导轨支架", "连接板", "螺丝"]},
            {"name": "钢带类", "children": ["钢带"]},
            {"name": "电缆线类", "children": ["随行电缆", "门锁电缆", "安全回路电缆"]},
            {"name": "外呼部件", "children": ["外呼显示板", "外呼板"]},
        ],
    },
    {
        "name": "底坑部件",
        "children": [
            {"name": "底坑检修盒类", "children": ["检修开关"]},
            {"name": "缓冲器类", "children": ["缓冲器", "缓冲器开关"]},
            {"name": "涨紧装置类", "children": ["张紧轮", "整套张紧装置"]},
            {"name": "安全钳类", "children": ["安全钳"]},
            {"name": "导靴类", "children": ["导靴轮", "导靴"]},
        ],
    },
    {
        "name": "厅轿门部件",
        "children": [
            {"name": "门电机类", "children": ["门电机", "电机轮"]},
            {"name": "门机变频器类", "children": ["门机变频器"]},
            {"name": "地坎类", "children": ["地坎"]},
            {"name": "门板类", "children": ["厅门板", "轿门板"]},
            {"name": "门头类", "children": ["厅门门头", "轿门门头", "门头钢丝绳", "门挂板", "锁钩", "门锁装置"]},
            {"name": "门轮类", "children": ["门挂轮"]},
            {"name": "门刀类", "children": ["门刀"]},
            {"name": "门机皮带类", "children": ["门机皮带"]},
        ],
    },
    {"name": "其他机械类", "children": [{"name": "其他机械类", "children": ["砝码"]}]},
    {"name": "其他电子类", "children": []},
    {"name": "扶梯配件", "children": []},
    {"name": "对讲类", "children": [{"name": "对讲类", "children": ["无线对讲", "有线对讲"]}]},
]

PRODUCT_TYPE_VALUES = [
    third
    for first in PRODUCT_CLASSIFICATION_TREE
    for second in first["children"]
    for third in second["children"]
]

CLASSIFICATION_FILE = LOG_DIR / "product_classifications.json"


def refresh_product_type_values():
    """分类树变更后刷新允许写入的三级分类集合。"""
    PRODUCT_TYPE_VALUES[:] = [
        third
        for first in PRODUCT_CLASSIFICATION_TREE
        for second in first["children"]
        for third in second["children"]
    ]


def load_classification_tree():
    """优先加载运行期间新增的分类；首次运行使用内置方案。"""
    global PRODUCT_CLASSIFICATION_TREE
    if not CLASSIFICATION_FILE.exists():
        return
    try:
        with open(CLASSIFICATION_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, list):
            PRODUCT_CLASSIFICATION_TREE = stored
            refresh_product_type_values()
    except Exception as e:
        logger.warning(f"[分类树] 读取持久化分类失败，使用默认方案 | error={e}")


def save_classification_tree():
    with open(CLASSIFICATION_FILE, "w", encoding="utf-8") as f:
        json.dump(PRODUCT_CLASSIFICATION_TREE, f, ensure_ascii=False, indent=2)


load_classification_tree()

# ========== 字段映射 ==========
FIELD_LABELS = {
    "id": "ID",
    "sku_code": "SKU编码",
    "product_name": "产品名称",
    "product_type": "产品分类",
    "product_brand": "产品品牌",
    "model": "型号",
    "supplier": "供应商",
    "warranty": "质保",
    "applicable_elevator_brand": "适用电梯品牌",
    "nature": "性质",
    "substitute_model": "替代型号",
    "precautions": "注意事项",
    "category": "品类归属",
    "technical_params": "技术参数",
    "purchase_cost": "采购成本价",
    "purchase_special_invoice": "进项专票",
    "purchase_general_invoice": "进项普票",
    "purchase_shipping": "采购运费",
    "retail_price": "零售价格",
    "retail_ladder_price": "零售阶梯价",
    "retail_tax": "零售税费",
    "retail_shipping": "零售运费",
    "remark": "备注",
    "daily_cutoff_time": "每日截单时间",
    "quote_validity": "报价有效期",
    "shipping_origin": "发货地",
    "shipping_time": "发货时间",
    "remark_2": "备注(2)",
    "updater": "更新人",
    "key_part_images": "关键部位图片",
    "actual_photos": "实物图照片",
    "product_image_3": "商品图片3",
    "product_image_4": "商品图片4",
    "product_image_5": "商品图片5",
    "product_image_6": "商品图片6",
    "product_image_7": "商品图片7",
    "product_image_8": "商品图片8",
    "product_image_9": "商品图片9",
    "product_image_10": "商品图片10",
    "product_detail_images": "商品详情图片",
    "filler": "填报人",
    "update_time": "更新时间",
    "filler_2": "填报人(2)",
    "update_time_2": "更新时间(2)",
    "filler_ip": "填报IP",
}

IMAGE_FIELDS = [
    "key_part_images", "actual_photos",
    "product_image_3", "product_image_4", "product_image_5",
    "product_image_6", "product_image_7", "product_image_8",
    "product_image_9", "product_image_10", "product_detail_images",
]

CREATE_PRODUCT_FIELDS = [
    "product_name", "product_brand", "model",
    "supplier", "warranty", "applicable_elevator_brand", "nature",
    "substitute_model", "precautions", "product_type",
    "technical_params", "remark", "remark_2",
    "purchase_cost", "purchase_special_invoice",
    "purchase_general_invoice", "purchase_shipping",
] + IMAGE_FIELDS

MAIN_FIELDS = [
    "sku_code", "product_name", "product_brand", "model",
    "supplier", "warranty", "applicable_elevator_brand", "nature",
    "substitute_model", "precautions", "category", "technical_params",
    "purchase_cost", "purchase_special_invoice", "purchase_general_invoice",
    "purchase_shipping", "retail_price", "retail_ladder_price",
    "retail_tax", "retail_shipping", "remark", "daily_cutoff_time",
    "quote_validity", "shipping_origin", "shipping_time", "remark_2",
    "updater", "filler", "update_time", "filler_2", "update_time_2", "filler_ip",
]
