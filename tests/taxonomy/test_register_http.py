from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from edna2dwc.common.version import DISTRIBUTION_NAME, installed_version
from edna2dwc.taxonomy import api_usage, register_http


class RegisterDown(RuntimeError):
    pass


@pytest.fixture
def waits(monkeypatch) -> list[float]:
    seen: list[float] = []
    monkeypatch.setattr(register_http, "sleep", seen.append)
    return seen


def _get(handler) -> httpx.Response:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return register_http.get(
        client, "https://register.test/match", register="test", error=RegisterDown
    )


def _fails_once_with(failure: httpx.Response):
    attempts = []

    def handler(request):
        attempts.append(1)
        return failure if len(attempts) == 1 else httpx.Response(200, json={})

    return handler


def test_backoff_doubles_to_about_two_minutes_before_giving_up(waits):
    with pytest.raises(RegisterDown):
        _get(lambda request: httpx.Response(503))

    assert waits == [2, 4, 8, 16, 32, 64]


def test_retry_after_in_seconds_is_honoured_on_429(waits):
    _get(_fails_once_with(httpx.Response(429, headers={"Retry-After": "45"})))

    assert waits == [45]


def test_retry_after_as_a_date_is_honoured_on_503(waits):
    when = datetime.now(UTC) + timedelta(seconds=30)
    _get(_fails_once_with(httpx.Response(503, headers={"Retry-After": format_datetime(when)})))

    assert 25 < waits[0] <= 30


def test_retry_after_as_a_date_with_no_zone_is_read_as_utc(waits):
    when = (datetime.now(UTC) + timedelta(seconds=30)).strftime("%a, %d %b %Y %H:%M:%S -0000")
    _get(_fails_once_with(httpx.Response(429, headers={"Retry-After": when})))

    assert 25 < waits[0] <= 30


def test_retry_after_never_waits_past_the_cap(waits):
    _get(_fails_once_with(httpx.Response(429, headers={"Retry-After": "3600"})))

    assert waits == [register_http.MAX_WAIT_SECONDS]


def test_an_unreadable_retry_after_falls_back_to_the_backoff(waits):
    _get(_fails_once_with(httpx.Response(503, headers={"Retry-After": "soon"})))

    assert waits == [2]


def test_a_rejected_request_fails_at_once_and_names_the_status(waits):
    with pytest.raises(RegisterDown, match="404"):
        _get(lambda request: httpx.Response(404))

    assert waits == []


def test_a_timeout_is_retried(waits):
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={})

    assert _get(handler).status_code == 200
    assert waits == [2]


def test_each_failed_attempt_is_counted_by_how_it_failed(waits):
    api_usage.reset()
    with pytest.raises(RegisterDown):
        _get(lambda request: httpx.Response(429))

    assert api_usage.counts() == {"test failed: HTTP 429 Too Many Requests": len(waits) + 1}


def test_every_request_names_the_tool_and_its_version():
    user_agents = []

    def handler(request):
        user_agents.append(request.headers["User-Agent"])
        return httpx.Response(200, json={})

    _get(handler)

    assert user_agents[0].startswith(f"{DISTRIBUTION_NAME}/{installed_version()} ")
