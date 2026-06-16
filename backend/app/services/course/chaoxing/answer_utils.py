import os
import re

from loguru import logger

from .decode import ENABLE_LOCAL_OCR, _ocr_image_to_text, is_vision_ocr_enabled


def _has_any_ocr_backend() -> bool:
    """True if ANY OCR backend is usable (local Paddle, external vision, or HTTP).

    Mirrors decode._ocr_image_to_text's `has_any_ocr` gate so question-title OCR
    is applied whenever it can succeed — not only when LOCAL OCR is on.
    """
    return bool(ENABLE_LOCAL_OCR or is_vision_ocr_enabled() or os.environ.get("CHAOXING_OCR_ENDPOINT", "").strip())


def _strip_json_block(md_str: str) -> str:
    """去掉Markdown代码块包裹，返回纯JSON字符串"""
    if not isinstance(md_str, str):
        return ""
    pattern = r"^\s*```(?:json)?\s*(.*?)\s*```\s*$"
    match = re.search(pattern, md_str, re.DOTALL)
    return match.group(1).strip() if match else md_str.strip()


def _ensure_answer_list(value) -> list[str]:
    """确保返回答案列表，兼容字符串、列表等多种格式"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _prepare_option_lines(options) -> list[str]:
    if not options:
        return []
    if isinstance(options, str):
        raw = options.splitlines()
    elif isinstance(options, (list, tuple, set)):
        raw = options
    else:
        raw = [str(options)]
    cleaned = []
    for item in raw:
        item_str = str(item).strip()
        if item_str:
            cleaned.append(item_str)
    return cleaned


def _clean_option_prefix(option: str) -> str:
    return re.sub(r"^[A-Za-z]\.?,?、?\s*", "", option).strip()


_IMG_TAG_PATTERN = re.compile(r'<img[^>]*src=["\'](.*?)["\'][^>]*>', re.IGNORECASE)


def _apply_ocr_to_title_if_needed(q_info: dict) -> None:
    """在题目标题中检测图片链接，并在本地 OCR 启用时用识别文本替换图片标签。

    仅处理作业题目的标题字符串，不影响其他阅读类内容；
    当 OCR 不可用或识别失败时，不修改原始标题。
    """
    if not _has_any_ocr_backend():
        return

    title = q_info.get("title")
    if not isinstance(title, str) or "<img" not in title:
        return

    def _repl(match: re.Match) -> str:
        src = match.group(1) or ""
        # 只处理超星题目图片的域名，避免误伤其他内容
        if "p.ananas.chaoxing.com" not in src:
            return match.group(0)

        text = ""
        try:
            text = _ocr_image_to_text(src) or ""
        except Exception as exc:
            logger.debug(f"题目图片 OCR 调用异常: {exc}")

        if text:
            return f"[公式: {text}]"
        # OCR 失败时也不要把裸露的 <img> 标签发给大模型，改为通用占位符
        return "[公式图片]"

    new_title = _IMG_TAG_PATTERN.sub(_repl, title)
    if new_title != title:
        logger.debug(f"题目图片 OCR 处理后标题：{new_title}")
        q_info["title"] = new_title
