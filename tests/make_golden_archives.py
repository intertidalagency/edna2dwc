from __future__ import annotations

import argparse
import contextlib
from pathlib import Path
import shutil
import tempfile

from edna2dwc.cli import app

GOLDEN_DIR = Path(__file__).parent / "golden"
CASES = sorted(path.name for path in GOLDEN_DIR.iterdir() if path.is_dir())
INPUTS = ("occurrence_long.tsv", "answers.yaml")
LOCK = "resolved_taxonomy.tsv"
ARCHIVE = "dwca.zip"


class GoldenBuildFailed(Exception):
    pass


def _run(argv: list[str]):
    return app(argv, result_action="return_value", exit_on_error=False, print_error=False)


def build_archive(case_dir: Path, work_dir: Path, *, resolve_live: bool = False) -> Path:
    for name in INPUTS if resolve_live else (*INPUTS, LOCK):
        shutil.copy(case_dir / name, work_dir / name)
    with contextlib.chdir(work_dir):
        if resolve_live:
            _run(["resolve-taxonomy"])
        result = _run(["build", "--automatic"])
    if result.status != "ok":
        raise GoldenBuildFailed(f"{case_dir.name}: {result.render()}")
    return work_dir / "archive" / ARCHIVE


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the golden archives in tests/golden/.")
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="Ask WoRMS and GBIF again and rewrite each case's resolved_taxonomy.tsv.",
    )
    args = parser.parse_args()
    for case in CASES:
        case_dir = GOLDEN_DIR / case
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            archive = build_archive(case_dir, work_dir, resolve_live=args.resolve)
            if args.resolve:
                shutil.copy(work_dir / LOCK, case_dir / LOCK)
            shutil.copy(archive, case_dir / ARCHIVE)
        print(f"{case}: wrote {case_dir / ARCHIVE}")


if __name__ == "__main__":
    main()
