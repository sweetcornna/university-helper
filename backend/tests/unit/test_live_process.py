"""Regression tests for live-minute submission retry handling (BE-043)."""

import pytest

from app.services.course.chaoxing import live_process


class FakeLive:
    name = "test live"

    def __init__(self, finish_results):
        self._finish_results = iter(finish_results)
        self.finish_calls = 0

    def get_status(self):
        return {"temp": {"data": {"duration": 60}}}

    def do_finish(self):
        self.finish_calls += 1
        return next(self._finish_results)


def _patch_sleep(monkeypatch):
    sleep_calls = []

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    monkeypatch.setattr(live_process.asyncio, "sleep", fake_sleep)
    return sleep_calls


@pytest.mark.asyncio
async def test_first_finish_success_is_called_once_and_returns_true(monkeypatch):
    live = FakeLive([True])
    sleep_calls = _patch_sleep(monkeypatch)

    result = await live_process.LiveProcessor.run_live(live, speed=2.0)

    assert result is True
    assert live.finish_calls == 1
    assert sleep_calls == [1.0] * 29 + [0.5]


@pytest.mark.asyncio
async def test_failed_finish_retries_once_and_succeeds(monkeypatch):
    live = FakeLive([False, True])
    sleep_calls = _patch_sleep(monkeypatch)

    result = await live_process.LiveProcessor.run_live(live)

    assert result is True
    assert live.finish_calls == 2
    assert sleep_calls == [0.5] * 10 + [1.0] * 59


@pytest.mark.asyncio
async def test_failed_finish_and_retry_returns_false_without_remaining_wait(monkeypatch):
    live = FakeLive([False, False])
    sleep_calls = _patch_sleep(monkeypatch)

    result = await live_process.LiveProcessor.run_live(live)

    assert result is False
    assert live.finish_calls == 2
    assert sleep_calls == [0.5] * 10


@pytest.mark.asyncio
async def test_stop_during_retry_wait_returns_false_without_retry(monkeypatch):
    live = FakeLive([False, True])
    stop = False
    sleep_calls = []

    async def fake_sleep(delay):
        nonlocal stop
        sleep_calls.append(delay)
        if len(sleep_calls) == 10:
            stop = True

    monkeypatch.setattr(live_process.asyncio, "sleep", fake_sleep)

    result = await live_process.LiveProcessor.run_live(live, should_stop=lambda: stop)

    assert result is False
    assert live.finish_calls == 1
    assert sleep_calls == [0.5] * 10
