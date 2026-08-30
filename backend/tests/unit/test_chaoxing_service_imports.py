"""Import-direction and compatibility checks for Chaoxing service modules."""

import ast
import pickle
from pathlib import Path

from api.base import SessionManager as LegacySessionManager
from api.config import GlobalConst as LegacyGlobalConst
from api.cookies import use_cookies as legacy_use_cookies
from api.cxsecret_font import decrypt as legacy_decrypt
from api.cxsecret_font import font2map as legacy_font2map
from api.exceptions import FontDecodeError as LegacyFontDecodeError
from api.font_decoder import FontDecoder as LegacyFontDecoder
from api.live import Live as LegacyLive
from api.vision_ocr import is_vision_ocr_enabled as legacy_is_vision_ocr_enabled
from api.vision_ocr import vision_ocr as legacy_vision_ocr
from app.services.course.chaoxing.config import GlobalConst
from app.services.course.chaoxing.cookies import use_cookies
from app.services.course.chaoxing.cxsecret_font import decrypt, font2map
from app.services.course.chaoxing.exceptions import FontDecodeError
from app.services.course.chaoxing.font_decoder import FontDecoder
from app.services.course.chaoxing.live import Live
from app.services.course.chaoxing.session_manager import SessionManager
from app.services.course.common.ocr import is_vision_ocr_enabled, vision_ocr

SERVICE_ROOT = Path(__file__).resolve().parents[2] / "app/services/course/chaoxing"
SERVICE_FILES = (
    "cipher.py",
    "cxsecret_font.py",
    "decode.py",
    "font_decoder.py",
    "live.py",
    "live_process.py",
)


def _legacy_import_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and node.module.startswith("api"):
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names if alias.name.startswith("api"))
    return modules


def test_service_import_graph_has_no_legacy_edges_except_logger():
    legacy_edges = {module for filename in SERVICE_FILES for module in _legacy_import_modules(SERVICE_ROOT / filename)}

    # api.logger is intentionally retained as the compatibility logger with its
    # loguru fallback; all canonical implementations must be imported locally.
    assert legacy_edges <= {"api.logger"}


def test_legacy_shims_reexport_canonical_objects_and_keep_pickle_paths():
    pairs = (
        (LegacyGlobalConst, GlobalConst),
        (LegacySessionManager, SessionManager),
        (legacy_use_cookies, use_cookies),
        (LegacyFontDecodeError, FontDecodeError),
        (legacy_font2map, font2map),
        (legacy_decrypt, decrypt),
        (LegacyFontDecoder, FontDecoder),
        (LegacyLive, Live),
        (legacy_is_vision_ocr_enabled, is_vision_ocr_enabled),
        (legacy_vision_ocr, vision_ocr),
    )

    for legacy, canonical in pairs:
        assert legacy is canonical
        assert pickle.loads(pickle.dumps(canonical)) is canonical
