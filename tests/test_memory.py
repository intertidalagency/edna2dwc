from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from edna2dwc.common.table import MEMORY_LIMIT_ENV
from tests.large_conversion import ASSEMBLE, BUILD, COMPARE, NARROW, WIDE, write_conversion

pytestmark = [
    pytest.mark.memory,
    pytest.mark.skipif(
        sys.platform != "linux",
        reason="the bound is for Linux, where containers run: DuckDB elsewhere uses the system "
        "allocator, which keeps freed memory, so its peak is higher though still bounded",
    ),
]

LIMIT_MIB = 512
MARGIN_MIB = 512
PEAK_OF_COMMAND = """
import resource, sys
from edna2dwc.cli import main
try:
    main()
finally:
    print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, file=sys.stderr)
"""


def _peak_mib(directory: Path, argv: list[str]) -> int:
    done = subprocess.run(
        [sys.executable, "-c", PEAK_OF_COMMAND, *argv],
        cwd=directory,
        env={**os.environ, MEMORY_LIMIT_ENV: f"{LIMIT_MIB}MiB"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return int(done.stderr.strip().splitlines()[-1]) >> 10


@pytest.mark.parametrize(
    ("rows", "shape"),
    [(200_000, NARROW), (2_000_000, NARROW), (300_000, WIDE)],
    ids=["200k narrow rows", "2M narrow rows", "300k wide rows"],
)
def test_a_conversion_stays_within_the_memory_limit_however_many_rows_or_columns_it_has(
    tmp_path, rows, shape
):
    write_conversion(tmp_path, rows, shape)
    peaks = {argv[0]: _peak_mib(tmp_path, argv) for argv in (ASSEMBLE, BUILD, COMPARE)}
    assert max(peaks.values()) < LIMIT_MIB + MARGIN_MIB, peaks
    codes = {finding["code"] for finding in json.loads((tmp_path / "findings.json").read_text())}
    assert ("DERIVED_VALUE_REPLACED" in codes) == shape.every_row_corrected
