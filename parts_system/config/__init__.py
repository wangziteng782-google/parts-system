"""配置包：数据库、七牛云、分类树、字段映射等常量。"""

from .constants import *  # noqa: F401,F403

__all__ = [
    "PROJECT_ROOT", "LOG_DIR", "logger",
    "DB_CONFIG", "OA_DB_CONFIG",
    "QINIU_CONFIG", "MAX_UPLOAD_IMAGE_SIZE", "MAX_UPLOAD_IMAGE_COUNT",
    "ALLOWED_IMAGE_MIME_TYPES",
    "PRODUCT_CLASSIFICATION_TREE", "PRODUCT_TYPE_VALUES", "CLASSIFICATION_FILE",
    "refresh_product_type_values", "load_classification_tree", "save_classification_tree",
    "FIELD_LABELS", "IMAGE_FIELDS", "CREATE_PRODUCT_FIELDS", "MAIN_FIELDS",
]
