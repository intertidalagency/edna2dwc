from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
import sys
import threading
import time

QUIET_ENV = "EDNA2DWC_QUIET"

NOMINAL_SECONDS_PER_BATCH = 8.0

MIN_SECONDS_BETWEEN_LINES = 5.0


def is_quiet() -> bool:
    return os.environ.get(QUIET_ENV, "") not in ("", "0")


def set_quiet(quiet: bool) -> None:
    if quiet:
        os.environ[QUIET_ENV] = "1"
    else:
        os.environ.pop(QUIET_ENV, None)


def emit(text: str) -> None:
    if is_quiet():
        return
    print(text, file=sys.stderr, flush=True)


def format_count(value: int) -> str:
    return f"{value:,}"


def format_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 120:
        return f"{minutes:.0f} min"
    hours, remainder = divmod(int(minutes), 60)
    return f"{hours}h {remainder:02d}m"


def format_clock(seconds: float) -> str:
    total = int(max(0.0, seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


@dataclass(frozen=True)
class LookupEstimate:
    distinct_names: int
    cached: int
    batches: int
    concurrency: int

    @property
    def uncached(self) -> int:
        return self.distinct_names - self.cached

    @property
    def nominal_seconds(self) -> float:
        if self.concurrency <= 0:
            return 0.0
        waves = self.batches / self.concurrency
        return waves * NOMINAL_SECONDS_PER_BATCH


def report_lookups(estimate: LookupEstimate, *, stage: str, follow_up_ceiling: int = 0) -> None:
    emit(f"{stage}: {format_count(estimate.distinct_names)} distinct names")
    if estimate.uncached == 0:
        emit(
            "  all cached, no lookup for these names. Their verdicts are what the register "
            "last said; --refresh to check them again"
        )
    else:
        emit(
            f"  {format_count(estimate.cached)} cached, "
            f"{format_count(estimate.uncached)} to look up "
            f"-> {format_count(estimate.batches)} requests, {estimate.concurrency} at a time"
        )
        emit(
            f"  rough estimate {format_duration(estimate.nominal_seconds)}, refined once it starts"
        )
    if follow_up_ceiling:
        emit(f"  up to {format_count(follow_up_ceiling)} more names if these find no match")


class BatchProgress:
    def __init__(
        self,
        *,
        total_batches: int,
        stage: str,
        unit: str = "names",
        now: Callable[[], float] = time.monotonic,
    ):
        self._total_batches = total_batches
        self._stage = stage
        self._unit = unit
        self._now = now
        self._lock = threading.Lock()
        self._done_batches = 0
        self._done_names = 0
        self._started = self._clock()
        self._last_line = 0.0

    def _clock(self) -> float:
        return self._now()

    def advance(self, names: int) -> None:
        with self._lock:
            self._done_batches += 1
            self._done_names += names
            elapsed = self._clock() - self._started
            is_edge = self._done_batches in (1, self._total_batches)
            if not is_edge and elapsed - self._last_line < MIN_SECONDS_BETWEEN_LINES:
                return
            self._last_line = elapsed
            line = self._render(elapsed)
        emit(line)

    def _render(self, elapsed: float) -> str:
        width = len(str(self._total_batches))
        counter = f"[{self._done_batches:>{width}}/{self._total_batches}]"
        parts = [
            f"  {counter}",
            f"{format_count(self._done_names)} {self._unit}",
            f"{format_clock(elapsed)} elapsed",
        ]
        remaining = self._remaining_seconds(elapsed)
        if remaining is not None:
            parts.append(f"~{format_duration(remaining)} left")
        return "  ".join(parts)

    def _remaining_seconds(self, elapsed: float) -> float | None:
        if self._done_batches == 0 or self._done_batches >= self._total_batches:
            return None
        per_batch = elapsed / self._done_batches
        remaining = per_batch * (self._total_batches - self._done_batches)
        if remaining < 1.0:
            return None
        return remaining

    def finish(self) -> None:
        took = format_clock(self._clock() - self._started)
        emit(f"{self._stage}: {format_count(self._done_names)} {self._unit} in {took}")
