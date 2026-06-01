"""Compatibility shim for the external vision-OCR feature.

Historically this module was a hardcoded no-op stub (is_vision_ocr_enabled()
always False, vision_ocr() always None), which silently disabled the entire
external vision-OCR path: decode.py imports these names, so operators who set
CHAOXING_VISION_OCR_PROVIDER + CHAOXING_VISION_OCR_KEY had their config ignored.

Like the other backend/api/* bridges, this now re-exports the real, unit-tested
implementation from app.services.course.common.ocr so the configured external
OCR actually runs in the live answering pipeline.
"""

from app.services.course.common.ocr import (  # noqa: F401
    is_vision_ocr_enabled,
    vision_ocr,
)

__all__ = ["is_vision_ocr_enabled", "vision_ocr"]
