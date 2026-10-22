from __future__ import annotations

import pytest

from edna2dwc.reproduce.compare import compare_archives, render_summary_markdown
from tests.make_golden_archives import ARCHIVE, CASES, GOLDEN_DIR, build_archive


@pytest.mark.parametrize("case", CASES)
def test_a_fresh_build_matches_the_golden_archive(case, tmp_path):
    case_dir = GOLDEN_DIR / case
    comparison = compare_archives(case_dir / ARCHIVE, build_archive(case_dir, tmp_path))
    assert not comparison.diverged, render_summary_markdown(comparison)
