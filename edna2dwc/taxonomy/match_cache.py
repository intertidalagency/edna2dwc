from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

SAVE_EVERY = 50


def _read(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _write_whole(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
    ) as temp:
        temp.write(text)
    os.replace(temp.name, path)


class MatchCache:
    def __init__(self, directory: Path | None, filename: str):
        self._path = None if directory is None else directory / filename
        self._entries = _read(self._path)
        self._unsaved = 0
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def __getitem__(self, key: str) -> Any:
        return self._entries[key]

    def add(self, entries: Mapping[str, Any]) -> None:
        with self._lock:
            self._entries.update(entries)
            self._unsaved += len(entries)
        self._save(min_unsaved=SAVE_EVERY)

    def save(self) -> None:
        self._save(min_unsaved=1)

    def _save(self, *, min_unsaved: int) -> None:
        if self._path is None:
            return
        with self._save_lock:
            snapshot = self._take_snapshot(min_unsaved)
            if snapshot is not None:
                _write_whole(self._path, json.dumps(snapshot, indent=2))

    def _take_snapshot(self, min_unsaved: int) -> dict[str, Any] | None:
        with self._lock:
            if self._unsaved < min_unsaved:
                return None
            self._unsaved = 0
            return dict(self._entries)
