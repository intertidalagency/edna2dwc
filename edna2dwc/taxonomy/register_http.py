from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import sleep

import httpx

from edna2dwc.common.version import DISTRIBUTION_NAME, installed_version
from edna2dwc.taxonomy import api_usage

TIMEOUT = 20.0
MAX_ATTEMPTS = 7
FIRST_BACKOFF_SECONDS = 2
MAX_WAIT_SECONDS = 120
RETRY_AFTER_STATUSES = (429, 503)
USER_AGENT = (
    f"{DISTRIBUTION_NAME}/{installed_version()} "
    "(+https://github.com/intertidalagency/edna2dwc; eDNA-to-DwC-A conversion)"
)


def _is_transient(status_code: int) -> bool:
    return status_code in (408, 429) or status_code >= 500


def _retry_after_seconds(response: httpx.Response) -> float | None:
    if response.status_code not in RETRY_AFTER_STATUSES:
        return None
    value = response.headers.get("Retry-After", "").strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _wait_before_retry(attempt: int, failure: Exception) -> float:
    asked = (
        _retry_after_seconds(failure.response)
        if isinstance(failure, httpx.HTTPStatusError)
        else None
    )
    backoff = FIRST_BACKOFF_SECONDS * 2**attempt
    return min(MAX_WAIT_SECONDS, backoff if asked is None else asked)


def get(
    client: httpx.Client, url: str, *, params=None, register: str, error: type[Exception]
) -> httpx.Response:
    failure: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.get(url, params=params, headers={"User-Agent": USER_AGENT})
            return response.raise_for_status()
        except httpx.HTTPStatusError as rejected:
            api_usage.record_failure(register, rejected)
            if not _is_transient(rejected.response.status_code):
                raise error(f"request to {url} was refused: {rejected}") from rejected
            failure = rejected
        except httpx.TransportError as unreachable:
            api_usage.record_failure(register, unreachable)
            failure = unreachable
        if attempt < MAX_ATTEMPTS - 1:
            sleep(_wait_before_retry(attempt, failure))
    raise error(f"request to {url} failed after {MAX_ATTEMPTS} attempts: {failure}") from failure
