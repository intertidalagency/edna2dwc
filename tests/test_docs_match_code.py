from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sys

import pytest
import yaml

from edna2dwc.build import packaging
from edna2dwc.cli.build import build_cmd
from edna2dwc.common.tsv import read_rows, write_tsv
from edna2dwc.conversion import artifacts
from edna2dwc.reproduce import bundle
from tests.make_golden_archives import GOLDEN_DIR
from tests.paths import REPO_ROOT

FILE_NAME = re.compile(r"\b(?:\w[\w-]*\.(?:yaml|tsv|json)|\w+/|justfile)")
NAMED = "a file answers.yaml names"
RAW = "a raw input"


def _passage(path: str, pattern: str) -> str:
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    match = re.search(pattern, text, re.DOTALL)
    assert match, f"{path} no longer says {pattern!r}"
    return match.group(1)


def _file_names(passage: str) -> set[str]:
    return set(FILE_NAME.findall(passage))


def _two_markers(directory: Path) -> Path:
    for name in ("occurrence_long.tsv", "answers.yaml", "resolved_taxonomy.tsv"):
        shutil.copy(GOLDEN_DIR / "two_markers" / name, directory / name)
    return directory


def _edit_answers(directory: Path, **changes) -> None:
    raw = yaml.safe_load((directory / artifacts.ANSWERS).read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            del raw["filters"][key]
        elif key in raw.get("filters", {}) or key in ("sample_metadata", "sample_type_col"):
            raw["filters"][key] = value
        else:
            raw[key] = value
    (directory / artifacts.ANSWERS).write_text(yaml.safe_dump(raw), encoding="utf-8")


def _bundle_categories(tmp_path: Path) -> set[str]:
    project = tmp_path / "project"
    (project / "confirmed").mkdir(parents=True)
    (project / "scripts").mkdir()
    (project / "raw").mkdir()
    (project / "proposed").mkdir()
    for name in (
        "conversion.yaml",
        "answers.yaml",
        "resolved_taxonomy.tsv",
        "audit_record.json",
        "samples.tsv",
        "confirmed/taxa.tsv",
        "scripts/read_inputs.py",
        "raw/counts.csv",
        "occurrence_long.tsv",
        "proposed/taxa.tsv",
        "findings.json",
        "term_mapping.tsv",
    ):
        (project / name).write_text("x\n", encoding="utf-8")
    (project / "conversion.yaml").write_text("steps: []\n", encoding="utf-8")
    justfile = tmp_path / "justfile"
    justfile.write_text("replay:\n", encoding="utf-8")
    collected = bundle.collect(
        project,
        justfile_path=justfile,
        raw_inputs=[Path("raw/counts.csv")],
        config_inputs=[Path("samples.tsv")],
    )
    special = {"samples.tsv": NAMED, "raw/counts.csv": RAW}
    categories = set()
    for arcname in collected.arcnames:
        inside = arcname.removeprefix(f"{artifacts.BUNDLE_DIR.as_posix()}/")
        directory, _, _ = inside.rpartition("/")
        categories.add(special.get(inside) or (f"{directory}/" if directory else inside))
    return categories


@pytest.mark.parametrize(
    ("path", "pattern"),
    [
        (
            "AGENTS.md",
            r"`reproduce/` holds exactly what a replay can't write again: (.*?)\. A replay",
        ),
        (
            "docs/reproducibility.md",
            r"`reproduce/` holds exactly what a replay can't write again: (.*?)\. A replay",
        ),
        (
            "docs/dev/architecture.md",
            r"holds what a replay needs and can't write again: (.*?)\. Everything else",
        ),
    ],
)
def test_what_reproduce_holds_is_what_the_bundle_collects(tmp_path, path, pattern):
    categories = _bundle_categories(tmp_path)
    passage = _passage(path, pattern)

    assert _file_names(passage) == categories - {NAMED, RAW}
    assert re.search(r"answers\.yaml`? names", passage), f"{path} omits {NAMED}"
    assert "raw input" in passage, f"{path} omits {RAW}"


def _files_build_reads(directory: Path) -> set[str]:
    before = {path.resolve() for path in directory.rglob("*") if path.is_file()}
    first_mode: dict[Path, str] = {}
    tracing = True

    def record(event: str, args: tuple) -> None:
        if tracing and event == "open" and isinstance(args[0], (str, os.PathLike)):
            first_mode.setdefault(Path(args[0]).resolve(), str(args[1]))

    sys.addaudithook(record)
    try:
        result = packaging.build(directory, automatic=True)
    finally:
        tracing = False
    assert result.status == "ok", result.detail
    root = directory.resolve()
    return {
        path.relative_to(root).as_posix()
        for path, mode in first_mode.items()
        if path in before and "r" in mode and "+" not in mode
    }


def _build_reads(tmp_path: Path) -> set[str]:
    directory = _two_markers(tmp_path)
    (directory / "conversion.yaml").write_text("steps: []\n", encoding="utf-8")
    written = (directory / artifacts.INTERMEDIATE).stat()
    (directory / artifacts.ASSEMBLY).write_text(
        json.dumps(
            {
                "intermediate": {"size": written.st_size, "mtime_ns": written.st_mtime_ns},
                "findings": [],
            }
        ),
        encoding="utf-8",
    )
    (directory / artifacts.AUDIT_RECORD).write_text('{"findings": []}\n', encoding="utf-8")
    (directory / "samples.tsv").write_text("sampleID\tsample_type\nS1\tsample\n", encoding="utf-8")
    (directory / "notes.txt").write_text("not an input\n", encoding="utf-8")
    _edit_answers(directory, sample_metadata="samples.tsv", sample_type_col="sample_type")
    packaging.build(directory, automatic=True)
    (directory / "confirmed").mkdir()
    header = (directory / "proposed" / "taxa.tsv").read_text(encoding="utf-8").splitlines()[0]
    (directory / "confirmed" / "taxa.tsv").write_text(f"{header}\n", encoding="utf-8")

    read = _files_build_reads(directory)
    categories = {f"{name.split('/')[0]}/" if "/" in name else name for name in read}
    return categories - {"samples.tsv"} | ({NAMED} if "samples.tsv" in read else set())


@pytest.mark.parametrize(
    ("source", "pattern"),
    [
        ("AGENTS.md", r"`build` recomputes the archive every time from (.*?)\. It keeps"),
        ("docs/dev/architecture.md", r"Each build reads (.*?), loads the table"),
        ("build --help", r"Build the archive from (.*?)\.\n"),
    ],
)
def test_what_build_reads_is_what_the_text_says_it_reads(tmp_path, monkeypatch, source, pattern):
    monkeypatch.chdir(tmp_path)
    read = _build_reads(tmp_path)
    if source == "build --help":
        match = re.search(pattern, build_cmd.__doc__ or "", re.DOTALL)
        assert match, f"{source} no longer says {pattern!r}"
        passage = match.group(1)
    else:
        passage = _passage(source, pattern)

    assert _file_names(passage) == read - {NAMED}
    assert re.search(r"answers\.yaml`?(?: and `?conversion\.yaml`?)? names?", passage), (
        f"{source} omits {NAMED}"
    )


def _asked_sections(tmp_path: Path) -> set[str]:
    directory = _two_markers(tmp_path)
    _edit_answers(directory, markers={}, controls={}, metadata={}, exclude_human=None)
    rows = list(read_rows(directory / artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["count"] = "0.25"
    write_tsv(rows, directory / artifacts.INTERMEDIATE, columns=list(rows[0]))

    result = packaging.build(directory)
    assert result.status == "needs_decision"
    sections = set()
    for missing in result.missing_answers:
        if missing.key.startswith("filters."):
            sections.add(missing.key)
        else:
            first, _, _ = missing.key.partition(".")
            sections.add(missing.key.rsplit(".", 1)[-1] if "constants" in missing.key else first)
    return sections


@pytest.mark.parametrize(
    ("path", "pattern"),
    [
        (
            "AGENTS.md",
            r"`build` stops until `answers.yaml` gives every answer it needs: (.*?)\. It writes",
        ),
        (
            "docs/commands.md",
            r"`build` stops before writing the archive if `answers.yaml` lacks (.*?)\. It asks",
        ),
    ],
)
def test_the_answers_build_asks_for_are_the_ones_the_text_names(
    tmp_path, monkeypatch, path, pattern
):
    monkeypatch.chdir(tmp_path)
    asked = _asked_sections(tmp_path)
    passage = _passage(path, pattern)

    assert set(re.findall(r"`([\w.]+)`", passage)) == asked
