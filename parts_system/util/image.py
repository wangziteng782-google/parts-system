"""图片 URL 处理工具。"""

import json
import re


def clean_image_urls(value):
    """清洗图片 URL：替换转义反斜杠、修复双斜杠"""
    if not value:
        return value
    cleaned = value.replace("\\/", "/")
    cleaned = re.sub(r"(?<!:)//", "/", cleaned)
    return cleaned


def parse_image_urls(value):
    """兼容 JSON 数组、单个 URL 和历史逗号/换行分隔格式。"""
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        if isinstance(parsed, str) and parsed.strip():
            return [parsed.strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return [item.strip() for item in re.split(r"[\r\n,]+", text) if item.strip()]
