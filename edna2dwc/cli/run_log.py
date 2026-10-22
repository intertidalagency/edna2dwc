from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import time

from edna2dwc.common.result import CommandResult
from edna2dwc.common.version import installed_version
from edna2dwc.taxonomy import api_usage

LOG_ENV = "EDNA2DWC_LOG"

_entry: dict = {}


def record_result(result: CommandResult) -> None:
    _entry["command"] = result.command
    _entry["status"] = result.status
    _entry["findings"] = [finding["code"] for finding in result.findings]


def record_error(error: BaseException) -> None:
    _entry["error"] = str(error)


def _exit_code(exit: SystemExit) -> int:
    if exit.code is None:
        return 0
    return exit.code if isinstance(exit.code, int) else 1


@contextmanager
def logging_invocation(argv: Sequence[str]) -> Generator[None]:
    if not os.environ.get(LOG_ENV):
        yield
        return
    log_path = Path(os.environ[LOG_ENV]).absolute()
    os.environ[LOG_ENV] = str(log_path)
    _entry.clear()
    _entry.update(
        started=datetime.now(UTC).isoformat(timespec="seconds"),
        argv=list(argv),
        version=installed_version(),
        findings=[],
    )
    api_usage.reset()
    started = time.monotonic()
    exit_code = 0
    try:
        yield
    except SystemExit as exit:
        exit_code = _exit_code(exit)
        raise
    except BaseException as error:
        exit_code = 1
        _entry.setdefault("error", f"{type(error).__name__}: {error}")
        _entry["crashed"] = True
        raise
    finally:
        _entry.update(
            seconds=round(time.monotonic() - started, 1),
            exit_code=exit_code,
            requests=api_usage.counts(),
        )
        _append(log_path, _entry)


def _append(log_path: Path, entry: dict) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry) + "\n")
    except OSError as error:
        print(f"{LOG_ENV}: could not write {log_path}: {error}", file=sys.stderr)
