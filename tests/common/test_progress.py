from __future__ import annotations

import threading

import pytest

from edna2dwc.common import progress
from edna2dwc.common.progress import (
    BatchProgress,
    LookupEstimate,
    emit,
    format_clock,
    format_duration,
    is_quiet,
    report_lookups,
    set_quiet,
)


@pytest.fixture(autouse=True)
def loud(monkeypatch):
    monkeypatch.delenv(progress.QUIET_ENV, raising=False)


def test_progress_goes_to_stderr_so_stdout_json_stays_parseable(capsys):
    emit("resolve-taxonomy: 3 distinct names")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "resolve-taxonomy: 3 distinct names\n"


def test_quiet_suppresses_output_and_round_trips(capsys):
    set_quiet(True)
    assert is_quiet()
    emit("suppressed")
    assert capsys.readouterr().err == ""

    set_quiet(False)
    assert not is_quiet()
    emit("shown")
    assert capsys.readouterr().err == "shown\n"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (9.4, "9s"),
        (59, "59s"),
        (60, "1 min"),
        (4200, "70 min"),
        (7199, "120 min"),
        (7200, "2h 00m"),
        (9000, "2h 30m"),
    ],
)
def test_format_duration_picks_the_coarsest_useful_unit(seconds, expected):
    assert format_duration(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00"), (134, "02:14"), (3600, "1:00:00"), (3725, "1:02:05")],
)
def test_format_clock_renders_elapsed_time(seconds, expected):
    assert format_clock(seconds) == expected


def test_lookup_report_names_the_counts_and_a_rough_duration(capsys):
    estimate = LookupEstimate(distinct_names=11257, cached=2155, batches=183, concurrency=4)
    report_lookups(estimate, stage="resolve-taxonomy")

    err = capsys.readouterr().err
    assert err == (
        "resolve-taxonomy: 11,257 distinct names\n"
        "  2,155 cached, 9,102 to look up -> 183 requests, 4 at a time\n"
        "  rough estimate 6 min, refined once it starts\n"
    )


def test_a_fully_cached_pass_speaks_only_for_the_names_it_was_handed(capsys):
    report_lookups(
        LookupEstimate(distinct_names=400, cached=400, batches=0, concurrency=4),
        stage="resolve-taxonomy",
    )

    err = capsys.readouterr().err
    cached_lines = [line for line in err.splitlines() if "all cached" in line]
    assert len(cached_lines) == 1
    assert "--refresh" in cached_lines[0]
    assert len(err.splitlines()) == 2


class FakeClock:
    def __init__(self):
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


def _bar(total_batches: int) -> tuple[BatchProgress, FakeClock]:
    clock = FakeClock()
    return BatchProgress(total_batches=total_batches, stage="resolve-taxonomy", now=clock), clock


def test_first_and_last_batch_always_print(capsys):
    bar, _ = _bar(3)

    bar.advance(50)
    bar.advance(50)
    bar.advance(50)

    lines = capsys.readouterr().err.strip().splitlines()
    assert len(lines) == 2
    assert "[1/3]" in lines[0]
    assert "[3/3]" in lines[1]


def test_middle_batches_are_throttled_until_the_interval_passes(capsys):
    bar, clock = _bar(100)

    bar.advance(50)
    capsys.readouterr()

    bar.advance(50)
    assert capsys.readouterr().err == ""

    clock.advance(progress.MIN_SECONDS_BETWEEN_LINES + 1)
    bar.advance(50)
    assert "[  3/100]" in capsys.readouterr().err


def test_a_progress_line_carries_measured_throughput_not_the_nominal(capsys):
    bar, clock = _bar(10)

    clock.advance(20)
    bar.advance(50)

    line = capsys.readouterr().err
    assert "50 names" in line
    assert "00:20 elapsed" in line
    assert "3 min" in line


def test_an_instant_first_batch_does_not_estimate_zero_left(capsys):
    bar, _ = _bar(10)

    bar.advance(50)

    line = capsys.readouterr().err
    assert "[ 1/10]" in line
    assert "left" not in line


def test_the_last_line_drops_the_estimate(capsys):
    bar, clock = _bar(1)

    clock.advance(8)
    bar.advance(50)

    assert "left" not in capsys.readouterr().err


def test_finish_reports_the_total(capsys):
    bar, clock = _bar(2)
    bar.advance(50)
    clock.advance(134)
    bar.advance(50)
    capsys.readouterr()

    bar.finish()

    err = capsys.readouterr().err
    assert "100 names" in err
    assert "02:14" in err


def test_advancing_from_many_threads_loses_no_batches(capsys):
    bar, _ = _bar(200)

    def work():
        for _ in range(50):
            bar.advance(50)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert "[200/200]" in capsys.readouterr().err
    bar.finish()
    assert "10,000 names" in capsys.readouterr().err
