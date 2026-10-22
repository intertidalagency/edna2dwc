import json

from cyclopts import CycloptsError
import pytest

from tests.paths import INPUT_FIXTURES


def test_inspect_reports_format_for_each_path_and_writes_the_page(run_cli, tmp_path):
    sample = INPUT_FIXTURES / "sample.tsv"
    result = run_cli(["inspect", str(sample), "-o", str(tmp_path)])
    assert result.exit_code == 0
    assert f"{sample}, format: delimited" in result.render()
    assert (
        f"Wrote {tmp_path / 'INSPECTION.md'} and {tmp_path / 'INSPECTION.html'}."
        in result.render()
    )
    page = (tmp_path / "INSPECTION.md").read_text(encoding="utf-8")
    assert str(sample) in page.splitlines()[0]


def test_inspect_json_is_a_list_of_reports(run_cli, tmp_path):
    result = run_cli(
        [
            "inspect",
            "--json",
            str(INPUT_FIXTURES / "sample.tsv"),
            str(INPUT_FIXTURES / "sample.xlsx"),
            "-o",
            str(tmp_path),
        ]
    )
    assert result.exit_code == 0
    assert [r["format"] for r in json.loads(result.render())] == ["delimited", "xlsx"]


def test_inspect_requires_at_least_one_path(run_cli):
    with pytest.raises(CycloptsError):
        run_cli(["inspect"])


def test_inspect_walks_a_directory_and_skips_hidden_files(run_cli, tmp_path):
    inputs = tmp_path / "input"
    (inputs / "documentation").mkdir(parents=True)
    (inputs / "table.csv").write_text("a,b\n1,2\n")
    (inputs / "documentation" / "notes.txt").write_text("hello\n")
    (inputs / ".DS_Store").write_bytes(b"\x00")
    result = run_cli(["inspect", str(inputs), "--json", "-o", str(tmp_path)])
    assert result.exit_code == 0
    reported = sorted(r["path"] for r in json.loads(result.render()))
    assert reported == [str(inputs / "documentation" / "notes.txt"), str(inputs / "table.csv")]
