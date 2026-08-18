"""七牛云工具函数。"""

from urllib.parse import quote

from ..config import QINIU_CONFIG


def qiniu_public_url(key):
    """构建七牛云公开访问 URL。"""
    domain = QINIU_CONFIG["domain"]
    if not domain.startswith(("http://", "https://")):
        domain = "https://" + domain
    return f"{domain}/{quote(key, safe='/')}"


def validate_qiniu_config():
    """检查七牛云配置是否完整，不完整则抛出 HTTPException。"""
    from fastapi import HTTPException

    missing = [
        env_name for key, env_name in (
            ("access_key", "QINIU_ACCESS_KEY"),
            ("secret_key", "QINIU_SECRET_KEY"),
            ("bucket", "QINIU_BUCKET"),
            ("domain", "QINIU_DOMAIN"),
        )
        if not QINIU_CONFIG[key]
    ]
    if missing:
        raise HTTPException(
            status_code=503,
            detail="七牛云尚未配置，请先设置：" + "、".join(missing),
        )
