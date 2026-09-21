import httpx
import pytest

from app.services.update_check import UpdateChecker, is_newer, parse_version, update_commands

URL = "https://api.github.com/repos/sweetcornna/university-helper/releases/latest"


def _release(tag="v1.4.8", **extra):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/sweetcornna/university-helper/releases/tag/{tag}",
        "body": "## Fixed\n- registration",
        "published_at": "2026-09-20T00:00:00Z",
        "draft": False,
        "prerelease": False,
        **extra,
    }


def _checker(handler, current="1.4.7", ttl=3600):
    return UpdateChecker(current, URL, ttl_seconds=ttl, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("candidate", "current", "expected"),
    [
        ("1.4.8", "1.4.7", True),
        ("v1.5.0", "1.4.7", True),
        ("1.4.7", "1.4.7", False),
        ("1.4.6", "1.4.7", False),
        ("1.5.0-rc.1", "1.4.7", True),
        ("1.5.0-rc.1", "1.5.0", False),
        ("nonsense", "1.4.7", False),
    ],
)
def test_version_ordering(candidate, current, expected):
    assert is_newer(candidate, current) is expected


def test_parse_version_rejects_garbage():
    assert parse_version("latest") is None


def test_update_commands_strip_v_prefix():
    assert update_commands("v1.4.8") == {
        "bash": "bash scripts/deploy_server.sh --tag 1.4.8 -y",
        "powershell": "pwsh scripts/deploy_server.ps1 -Tag 1.4.8 -Yes",
    }


@pytest.mark.asyncio
async def test_newer_release_is_reported_with_commands():
    checker = _checker(lambda request: httpx.Response(200, json=_release()))
    status = await checker.get_status()
    assert status["has_update"] is True
    assert status["latest"] == "1.4.8"
    assert status["commands"]["bash"].endswith("--tag 1.4.8 -y")
    assert "registration" in status["notes"]


@pytest.mark.asyncio
async def test_same_version_is_not_an_update():
    checker = _checker(lambda request: httpx.Response(200, json=_release("v1.4.7")))
    assert (await checker.get_status())["has_update"] is False


@pytest.mark.asyncio
async def test_prerelease_and_draft_are_ignored():
    checker = _checker(lambda request: httpx.Response(200, json=_release("v9.0.0", prerelease=True)))
    status = await checker.get_status()
    assert status["latest"] is None
    assert status["has_update"] is False


@pytest.mark.asyncio
async def test_network_failure_keeps_last_good_result():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=_release())
        raise httpx.ConnectTimeout("blocked")

    checker = _checker(handler, ttl=0)
    assert (await checker.get_status())["latest"] == "1.4.8"
    assert (await checker.get_status())["latest"] == "1.4.8"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_results_are_cached_for_the_ttl():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=_release())

    checker = _checker(handler)
    await checker.get_status()
    await checker.get_status()
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_long_notes_are_truncated():
    checker = _checker(lambda request: httpx.Response(200, json=_release(body="x" * 5000)))
    assert len((await checker.get_status())["notes"]) == 2000
