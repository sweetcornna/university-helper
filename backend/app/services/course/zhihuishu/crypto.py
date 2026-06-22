"""智慧树加密工具模块"""

import datetime as _datetime
import json as _json
import time as _time
from base64 import b64decode, b64encode

from Crypto.Cipher import AES

IV = b"1g3qqdh4jvbskb9x"
HOME_KEY = b"7q9oko0vqb3la20r"
AI_KEY = b"hw2fdlwcj4cs1mx7"
VIDEO_KEY = b"azp53h0kft7qi78q"
QA_KEY = b"kcGOlISPkYKRksSK"
EXAM_KEY = b"onbfhdyvz8x7otrp"


def encrypt_secret_str(payload=None, key: bytes = HOME_KEY, iv: bytes = IV) -> str:
    """Build the ``secretStr`` param required by Zhihuishu's AppInterfaceSign
    interceptor (``com.zhihuishu.starter.secret``).

    The server AES-CBC-decrypts ``secretStr`` and parses the result as a JSON
    *object*; a bare value is rejected with "can not cast to JSONObject", and an
    unsigned request is rejected with "aes加密参数异常". Verified live against
    queryShareCourseInfo with HOME_KEY → code 200.

    ``payload`` may be a dict (json-encoded) or a pre-serialized JSON-object str;
    when omitted a minimal ``{"dateFormate": <ms>}`` object is sent.
    """
    if payload is None:
        payload = {"dateFormate": int(_time.time() * 1000)}
    text = payload if isinstance(payload, str) else _json.dumps(payload, ensure_ascii=False)
    return Cipher(key, iv).encrypt(text)


def get_ev(data: list, key: str = "zzpttjd") -> str:
    """Build the ``ev`` / ``sdsew`` obfuscation param used by Zhihuishu's video
    progress-report endpoints (saveDatabaseIntervalTime / ...V2).

    The fields in ``data`` are ``';'``-joined, then each character is XOR-ed
    against a cyclically-repeating ``key`` and emitted as 2-hex-digit pairs.
    ``saveDatabaseIntervalTime`` uses the default key ``zzpttjd`` (the meet-course
    endpoint uses ``zhihuishu``). Ported verbatim from the upstream reference so
    the produced ``ev`` is byte-compatible with the live API.
    """

    def _key_stream():
        while True:
            for ch in key:
                yield ord(ch)

    stream = _key_stream()
    joined = ";".join(map(str, data))
    ev = ""
    for ch in joined:
        tmp = hex(ord(ch) ^ next(stream)).replace("0x", "")
        if len(tmp) < 2:
            tmp = "0" + tmp
        # upstream slices [-4:]; for a single byte this equals the 2-hex pair.
        ev += tmp[-4:]
    return ev


def hms(seconds: int) -> str:
    """Format a second count as ``H:MM:SS`` for the ``ev`` time field."""
    return str(_datetime.timedelta(seconds=int(seconds)))


class Cipher:
    """AES 加密解密器"""

    def __init__(self, key: bytes = VIDEO_KEY, iv: bytes = IV):
        self.key = key
        self.iv = iv

    @staticmethod
    def pad(data: str) -> bytes:
        padding_len = 16 - len(data) % 16
        return (data + chr(padding_len) * padding_len).encode()

    @staticmethod
    def unpad(data: bytes) -> str:
        data = data.decode()
        return data[: -ord(data[-1])]

    def encrypt(self, data: str) -> str:
        cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
        return b64encode(cipher.encrypt(self.pad(data))).decode()

    def decrypt(self, data: str) -> str:
        cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
        return self.unpad(cipher.decrypt(b64decode(data)))


class WatchPoint:
    """视频观看点记录器"""

    def __init__(self, init: int = 0):
        self.reset(init)

    def add(self, end: int, start: int = None):
        wp_interval = 2
        start = self.last if start is None else start
        end = int(end)
        self.last = end
        for i in range(start, end + 1, wp_interval):
            self.wp.append(self.gen(i))

    def get(self) -> str:
        return ",".join(map(str, self.wp))

    def reset(self, init: int = 0):
        self.wp = [0, 1]
        self.last = int(init) or 1

    @staticmethod
    def gen(time: int) -> int:
        return int(time // 5 + 2)
