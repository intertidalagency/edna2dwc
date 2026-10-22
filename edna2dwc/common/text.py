from __future__ import annotations

from collections.abc import Sequence


def first_few(items: Sequence[str], limit: int, total: int | None = None) -> str:
    total = len(items) if total is None else total
    shown = ", ".join(items[:limit])
    return shown if total <= limit else f"{shown} and {total - limit} more"
