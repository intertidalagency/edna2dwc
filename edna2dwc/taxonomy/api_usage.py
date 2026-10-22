from __future__ import annotations

from collections import Counter

_counts: Counter[str] = Counter()


def record(service: str, *, n: int = 1) -> None:


def counts() -> dict[str, int]:


def reset() -> None:
