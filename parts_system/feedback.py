"""销售商品反馈的公共枚举；数据库结构统一由 sql 迁移脚本维护。"""


FEEDBACK_TYPE_LABELS = {
    "price": "产品价格",
    "spec": "产品规格",
    "image": "产品图片",
    "other": "其他问题",
}

FEEDBACK_STATUSES = {"pending", "completed", "ignored"}
