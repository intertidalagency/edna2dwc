from __future__ import annotations

from pathlib import Path
import shutil

from edna2dwc.conversion import artifacts
from edna2dwc.conversion.answers import AnswersError


def empty(root: Path, out_dir: Path, inputs: list[Path]) -> None:
    archive = (root / out_dir).resolve()
    held = [path.as_posix() for path in inputs if (root / path).resolve().is_relative_to(archive)]
    if held:
        raise AnswersError(
            f"{artifacts.ANSWERS}: out_dir {out_dir.as_posix()!r} holds {', '.join(held)}, an "
            "input of this conversion. build empties out_dir every time, so choose a directory "
            "of its own, such as archive"
        )
    if not _written_by_build(root / out_dir):
        raise AnswersError(
            f"{artifacts.ANSWERS}: out_dir {out_dir.as_posix()!r} holds files build didn't "
            f"write. build empties out_dir every time, so it only empties a directory that is "
            f"empty or holds the {artifacts.BUNDLE_DIR.as_posix()}/ of an earlier build. Choose "
            "another out_dir, or move those files out of it"
        )
    remove(root / out_dir)


def remove(out_dir: Path) -> None:
    shutil.rmtree(out_dir, ignore_errors=True)


def withdraw(root: Path, out_dir: Path | None) -> None:
    if out_dir is not None and _holds_a_build(root / out_dir):
        (root / out_dir / artifacts.ZIP_NAME).unlink(missing_ok=True)


def _holds_a_build(directory: Path) -> bool:
    return (directory / artifacts.BUNDLE_DIR / artifacts.CONFIG).is_file()


def _written_by_build(directory: Path) -> bool:
    if not directory.exists():
        return True
    if not directory.is_dir():
        return False
    return _holds_a_build(directory) or not any(directory.iterdir())
