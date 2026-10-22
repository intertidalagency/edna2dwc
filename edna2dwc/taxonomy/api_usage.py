from __future__ import annotations

from collections import Counter
import threading

import httpx

_counts: Counter[str] = Counter()
_lock = threading.Lock()


def record(service: str, *, n: int = 1) -> None:
    with _lock:
        _counts[service] += n


def describe_failure(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code} {error.response.reason_phrase}"
    return type(error).__name__


def record_failure(register: str, error: Exception) -> None:
    record(f"{register} failed: {describe_failure(error)}")


def counts() -> dict[str, int]:
    with _lock:
        return dict(_counts)


def reset() -> None:
    with _lock:
        _counts.clear()
