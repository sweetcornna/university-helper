"""Unit tests for the Zhihuishu crypto helpers (AES secretStr signing + ev/sdsew
XOR obfuscation) that the corrected request protocol relies on."""

import json

from app.services.course.zhihuishu.crypto import (
    HOME_KEY,
    VIDEO_KEY,
    Cipher,
    encrypt_secret_str,
    get_ev,
    hms,
)


def test_get_ev_matches_reference_vector():
    """get_ev(';'.join) XOR-cycles the key 'zzpttjd' and emits 2-hex pairs.

    '1;2' XOR [122,122,112] => 0x4b,0x41,0x42 => '4b4142' (hand-computed against
    the upstream reference implementation).
    """
    assert get_ev(["1", "2"]) == "4b4142"
    # Non-string fields are stringified the same way (1 -> "1").
    assert get_ev([1, 2]) == "4b4142"


def test_get_ev_is_deterministic_and_hex():
    ev = get_ev(["recruit", "lesson", 0, "vid"])
    assert ev == get_ev(["recruit", "lesson", 0, "vid"])
    assert all(c in "0123456789abcdef" for c in ev)
    assert len(ev) % 2 == 0


def test_hms_formats_seconds():
    assert hms(65) == "0:01:05"
    assert hms(3661) == "1:01:01"
    assert hms(0) == "0:00:00"


def test_course_list_secret_str_roundtrips_under_home_key():
    payload = {"status": 0, "pageNo": 1, "pageSize": 5}
    secret = encrypt_secret_str(payload, key=HOME_KEY)
    decoded = json.loads(Cipher(HOME_KEY).decrypt(secret))
    assert decoded == payload


def test_video_secret_str_uses_distinct_key():
    payload = {"recruitAndCourseId": "rac-1"}
    secret = encrypt_secret_str(payload, key=VIDEO_KEY)
    # Correct key decrypts cleanly...
    assert json.loads(Cipher(VIDEO_KEY).decrypt(secret)) == payload
    # ...and the two endpoint keys are genuinely different.
    assert HOME_KEY != VIDEO_KEY
