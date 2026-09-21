"""Regression tests for bounded Chaoxing question-image OCR downloads."""

import importlib
import logging
import warnings
from unittest.mock import Mock

import pytest

_IMAGE_URL = "https://p.ananas.chaoxing.com/star3/question.png"
_PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c63f8ffff3f0005fe02fe0def46b80000000049454e44ae426082"
)


class _FakeResponse:
    def __init__(self, chunks, headers=None, status_code=200):
        self.chunks = list(chunks)
        self.headers = headers or {}
        self.status_code = status_code
        self.iterated_chunks = 0
        self.closed = False
        self.chunk_size = None

    def iter_content(self, chunk_size):
        self.chunk_size = chunk_size
        for chunk in self.chunks:
            self.iterated_chunks += 1
            yield chunk

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.headers = {}
        self.cookies = {}
        self.get_kwargs = None
        self.closed = False

    def get(self, _url, **kwargs):
        self.get_kwargs = kwargs
        return self.response

    def close(self):
        self.closed = True


def _prepare_external_ocr(monkeypatch, decode):
    monkeypatch.setattr(decode, "is_vision_ocr_enabled", lambda: True)
    vision_ocr = Mock(return_value="recognized")
    monkeypatch.setattr(decode, "vision_ocr", vision_ocr)
    return vision_ocr


def _prepare_download(monkeypatch, decode, response):
    session = _FakeSession(response)
    monkeypatch.setattr(decode.requests, "Session", lambda: session)
    return session


def _capture_decode_logs(monkeypatch, caplog, decode):
    """Route decode logs through caplog for secret/non-secret assertions."""
    capture_logger = logging.getLogger("test.chaoxing.decode.ocr")
    monkeypatch.setattr(decode, "logger", capture_logger)
    caplog.set_level(logging.DEBUG, logger=capture_logger.name)
    return capture_logger


def _captured_messages(caplog) -> str:
    return "\n".join(record.getMessage() for record in caplog.records)


@pytest.fixture
def decode_module():
    return importlib.import_module("app.services.course.chaoxing.decode")


def test_small_image_stream_is_passed_to_ocr_and_closed(monkeypatch, decode_module):
    vision_ocr = _prepare_external_ocr(monkeypatch, decode_module)
    response = _FakeResponse([_PNG_1X1], {"Content-Type": "image/png", "Content-Length": str(len(_PNG_1X1))})
    session = _prepare_download(monkeypatch, decode_module, response)

    assert decode_module._ocr_image_to_text(_IMAGE_URL) == "recognized"
    vision_ocr.assert_called_once_with(_PNG_1X1)
    assert response.closed
    assert session.closed
    assert session.get_kwargs["stream"] is True
    assert response.chunk_size == decode_module._OCR_STREAM_CHUNK_SIZE


@pytest.mark.parametrize(
    "url",
    [
        # Requests prepares the first URL as a request to 127.0.0.1; the
        # pre-parse guard must reject both raw and encoded authority smuggling.
        r"https://127.0.0.1\@p.ananas.chaoxing.com/path",
        "https://127.0.0.1%5c@p.ananas.chaoxing.com/path",
        "https://127.0.0.1%255c@p.ananas.chaoxing.com/path",
        "https://127.0.0.1%25255c@p.ananas.chaoxing.com/path",
        # Credentials are unnecessary for an image CDN and can obscure the
        # authority, including an empty userinfo marker.
        "https://@p.ananas.chaoxing.com/path",
        "https://user:password@p.ananas.chaoxing.com/path",
        # URL parser normalization must not make controls or malformed ports
        # disappear before validation.
        "https://p.ananas.chaoxing.com/path\nnext",
        "https://p.ananas.chaoxing.com:bad/path",
        "https://p.ananas.chaoxing.com:65536/path",
        "https://p.ananas.chaoxing.com:/path",
        # Reject Unicode/IDNA lookalikes and a terminal DNS dot explicitly.
        "https://p.ananas.chaoxing.com./path",
        "https://xn--p.ananas.chaoxing.com/path",
        "https://ｅ.ananas.chaoxing.com/path",
    ],
)
def test_ocr_url_validation_rejects_parser_smuggling_and_ambiguous_hosts(decode_module, url):
    assert decode_module._is_allowed_ocr_img_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/image.png",
        "https://127.0.0.1/image.png",
        r"https://127.0.0.1\@p.ananas.chaoxing.com/image.png",
    ],
)
def test_ocr_rejected_loopback_urls_do_not_create_cookie_session(monkeypatch, decode_module, url):
    vision_ocr = _prepare_external_ocr(monkeypatch, decode_module)
    session_factory = Mock()
    monkeypatch.setattr(decode_module.requests, "Session", session_factory)

    assert decode_module._ocr_image_to_text(url) == ""
    session_factory.assert_not_called()
    vision_ocr.assert_not_called()


def test_ocr_revalidates_requests_prepared_url_before_cookie_session(monkeypatch, decode_module):
    _prepare_external_ocr(monkeypatch, decode_module)
    prepared = decode_module.requests.Request(
        method="GET", url=r"https://127.0.0.1\@p.ananas.chaoxing.com/path"
    ).prepare()
    assert prepared.url.startswith("https://127.0.0.1/")

    session_factory = Mock()
    monkeypatch.setattr(decode_module.requests, "Session", session_factory)
    assert decode_module._prepare_allowed_ocr_img_url(prepared.url) is None
    assert decode_module._ocr_image_to_text(prepared.url) == ""
    session_factory.assert_not_called()


def test_ocr_rejection_log_does_not_include_url_or_query_token(monkeypatch, caplog, decode_module):
    _capture_decode_logs(monkeypatch, caplog, decode_module)
    sentinel_url = "https://127.0.0.1\\@p.ananas.chaoxing.com/image.png?token=URL_SENTINEL"

    assert decode_module._ocr_image_to_text(sentinel_url) == ""
    messages = _captured_messages(caplog)
    assert "URL_SENTINEL" not in messages
    assert sentinel_url not in messages


def test_ocr_download_exception_log_uses_type_without_exception_text(monkeypatch, caplog, decode_module):
    _prepare_external_ocr(monkeypatch, decode_module)
    _capture_decode_logs(monkeypatch, caplog, decode_module)
    session = Mock()
    session.headers = {}
    session.cookies = Mock()
    session.get.side_effect = RuntimeError("DOWNLOAD_EXCEPTION_SENTINEL")
    monkeypatch.setattr(decode_module.requests, "Session", lambda: session)

    assert decode_module._ocr_image_to_text(_IMAGE_URL) == ""
    messages = _captured_messages(caplog)
    assert "RuntimeError" in messages
    assert "DOWNLOAD_EXCEPTION_SENTINEL" not in messages


def test_ocr_response_and_result_logs_do_not_include_header_or_ocr_text(monkeypatch, caplog, decode_module):
    _capture_decode_logs(monkeypatch, caplog, decode_module)
    _prepare_external_ocr(monkeypatch, decode_module)
    response = _FakeResponse(
        [_PNG_1X1],
        {"Content-Type": "text/plain; token=RESPONSE_TOKEN_SENTINEL"},
    )
    _prepare_download(monkeypatch, decode_module, response)

    assert decode_module._ocr_image_to_text(_IMAGE_URL) == ""
    messages = _captured_messages(caplog)
    assert "RESPONSE_TOKEN_SENTINEL" not in messages

    # A successful OCR result is returned unchanged for callers, but must not
    # be copied into the log stream.
    caplog.clear()
    response = _FakeResponse([_PNG_1X1], {"Content-Type": "image/png"})
    _prepare_download(monkeypatch, decode_module, response)
    monkeypatch.setattr(decode_module, "vision_ocr", Mock(return_value="OCR_RESULT_SENTINEL"))

    assert decode_module._ocr_image_to_text(_IMAGE_URL) == "OCR_RESULT_SENTINEL"
    assert "OCR_RESULT_SENTINEL" not in _captured_messages(caplog)


def test_http_ocr_exception_log_does_not_include_endpoint_or_exception_text(monkeypatch, caplog, decode_module):
    _capture_decode_logs(monkeypatch, caplog, decode_module)
    monkeypatch.setattr(
        decode_module.requests,
        "post",
        Mock(side_effect=ValueError("HTTP_OCR_EXCEPTION_SENTINEL")),
    )
    endpoint = "https://ocr.example.test/recognize?token=OCR_ENDPOINT_TOKEN_SENTINEL"
    source_url = "https://p.ananas.chaoxing.com/path?token=IMAGE_URL_TOKEN_SENTINEL"

    assert decode_module._call_http_ocr(endpoint, b"image", source_url) == ""
    messages = _captured_messages(caplog)
    assert "OCR_ENDPOINT_TOKEN_SENTINEL" not in messages
    assert "IMAGE_URL_TOKEN_SENTINEL" not in messages
    assert "HTTP_OCR_EXCEPTION_SENTINEL" not in messages
    assert "ValueError" in messages


def test_non_image_mime_is_rejected_before_reading(monkeypatch, decode_module):
    _prepare_external_ocr(monkeypatch, decode_module)
    response = _FakeResponse([_PNG_1X1], {"Content-Type": "text/html"})
    _prepare_download(monkeypatch, decode_module, response)

    assert decode_module._ocr_image_to_text(_IMAGE_URL) == ""
    assert response.iterated_chunks == 0
    assert response.closed


def test_declared_oversized_content_length_is_rejected_before_reading(monkeypatch, decode_module):
    _prepare_external_ocr(monkeypatch, decode_module)
    response = _FakeResponse(
        [_PNG_1X1],
        {"Content-Type": "image/png", "Content-Length": str(decode_module._OCR_MAX_IMAGE_BYTES + 1)},
    )
    _prepare_download(monkeypatch, decode_module, response)

    assert decode_module._ocr_image_to_text(_IMAGE_URL) == ""
    assert response.iterated_chunks == 0
    assert response.closed


@pytest.mark.parametrize("content_length", [None, "1"])
def test_actual_stream_limit_handles_missing_or_spoofed_length(monkeypatch, decode_module, content_length):
    _prepare_external_ocr(monkeypatch, decode_module)
    monkeypatch.setattr(decode_module, "_OCR_MAX_IMAGE_BYTES", 8)
    headers = {"Content-Type": "image/png"}
    if content_length is not None:
        headers["Content-Length"] = content_length
    response = _FakeResponse([b"12345678", b"9", b"must-not-be-read"], headers)
    _prepare_download(monkeypatch, decode_module, response)

    assert decode_module._ocr_image_to_text(_IMAGE_URL) == ""
    assert response.iterated_chunks == 2
    assert response.closed


class _FakeBombError(Exception):
    pass


class _FakeBombWarning(Warning):
    pass


class _FakeImage:
    mode = "RGB"

    def __init__(self, size=(1, 1)):
        self.size = size
        self.closed = False
        self.loaded = False

    def load(self):
        self.loaded = True

    def close(self):
        self.closed = True


class _FakeImageModule:
    MAX_IMAGE_PIXELS = 123
    DecompressionBombError = _FakeBombError
    DecompressionBombWarning = _FakeBombWarning

    def __init__(self, image=None, error=None, warning=False):
        self.image = image or _FakeImage()
        self.error = error
        self.warning = warning

    def open(self, _stream):
        if self.error:
            raise self.error("bomb")
        if self.warning:
            warnings.warn("bomb warning", self.DecompressionBombWarning, stacklevel=2)
        return self.image


@pytest.mark.parametrize(
    ("image_module", "expected_loaded", "expected_closed"),
    [
        (_FakeImageModule(error=_FakeBombError), False, False),
        (_FakeImageModule(warning=True), False, False),
        (_FakeImageModule(image=_FakeImage(size=(9000, 1))), False, True),
    ],
)
def test_pillow_bombs_and_oversized_dimensions_fail_closed(
    monkeypatch, decode_module, image_module, expected_loaded, expected_closed
):
    _prepare_external_ocr(monkeypatch, decode_module)
    response = _FakeResponse([b"image"], {"Content-Type": "image/png"})
    _prepare_download(monkeypatch, decode_module, response)
    monkeypatch.setattr(decode_module, "PIL_AVAILABLE", True)
    monkeypatch.setattr(decode_module, "Image", image_module, raising=False)

    assert decode_module._ocr_image_to_text(_IMAGE_URL) == ""
    assert image_module.image.loaded is expected_loaded
    assert image_module.image.closed is expected_closed
    assert image_module.MAX_IMAGE_PIXELS == 123
    assert response.closed
