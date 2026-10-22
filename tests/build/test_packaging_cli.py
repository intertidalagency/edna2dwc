from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest
import yaml

from edna2dwc.build import packaging
from edna2dwc.cli.common import CommandLineError
from edna2dwc.common.table import ResourceLimitError
from tests.make_golden_archives import GOLDEN_DIR


@pytest.fixture(autouse=True)
def _conversion_dir(tmp_path, monkeypatch):
    for name in ("occurrence_long.tsv", "answers.yaml", "resolved_taxonomy.tsv"):
        shutil.copy(GOLDEN_DIR / "two_markers" / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)


def test_a_build_waiting_on_review_exits_0_and_names_the_status_and_the_review_page(run_cli):
    result = run_cli(["build"])
    assert result.exit_code == 0
    assert result.status == "needs_review"
    assert "REVIEW.md" in result.render()
    assert Path("REVIEW.md").exists()


def test_json_holds_every_finding_of_the_build_and_what_to_do_next(run_cli):
    reported = json.loads(run_cli(["build", "--json"]).render())
    written = [f["code"] for f in json.loads(Path("findings.json").read_text())]
    assert reported["status"] == "needs_review"
    assert [f["code"] for f in reported["findings"]] == written
    assert written[-1] == "PROPOSAL_OPEN"
    assert reported["outputs"]["archive_dir"] == "archive"
    assert "edna2dwc build" in reported["next"]


def test_json_says_what_to_do_next_when_the_build_stops_on_an_error(run_cli):
    Path("conversion.yaml").write_text("steps: []\nraw_inputs: [absent.xlsx]\n")
    reported = json.loads(run_cli(["build", "--automatic", "--json"]).render())
    assert reported["status"] == "error"
    assert reported["next"] == "fix the error above, then `edna2dwc build`"


def test_automatic_finishes_with_exit_0(run_cli):
    result = run_cli(["build", "--automatic"])
    assert result.exit_code == 0, result.render()
    assert result.status == "ok"
    assert Path("archive/dwca.zip").exists()


def test_unreadable_answers_are_a_usage_error_naming_the_key(run_cli):
    raw = yaml.safe_load(Path("answers.yaml").read_text())
    raw["environment"] = {}
    Path("answers.yaml").write_text(yaml.safe_dump(raw))
    with pytest.raises(CommandLineError, match="environment"):
        run_cli(["build"])


def test_a_missing_intermediate_table_is_a_usage_error(run_cli):
    Path("occurrence_long.tsv").unlink()
    with pytest.raises(CommandLineError, match="occurrence_long.tsv"):
        run_cli(["build"])


def test_a_recorded_audit_is_kept_beside_answers_yaml_and_bundled(run_cli):
    run_cli(["build"])
    Path("result.json").write_text(json.dumps({"findings": []}))
    run_cli(["audit", "record", "archive", "--from-file", "result.json"])
    run_cli(["build"])
    assert Path("audit_record.json").exists()
    assert Path("archive/reproduce/audit_record.json").exists()


def test_a_build_stopped_by_unreadable_answers_rewrites_the_review_page(run_cli):
    run_cli(["build", "--automatic"])
    Path("answers.yaml").write_text("dataset_id: [unclosed\n")
    with pytest.raises(CommandLineError):
        run_cli(["build"])
    review = Path("REVIEW.md").read_text()
    assert "Finished" not in review
    assert "answers.yaml" in review


def test_a_build_stopped_by_a_missing_table_rewrites_the_review_page(run_cli):
    run_cli(["build", "--automatic"])
    Path("occurrence_long.tsv").unlink()
    with pytest.raises(CommandLineError):
        run_cli(["build"])
    review = Path("REVIEW.md").read_text()
    assert "Finished" not in review
    assert "occurrence_long.tsv does not exist" in review


def test_a_build_stopped_on_a_question_exits_0_and_leaves_no_earlier_archive(run_cli):
    run_cli(["build", "--automatic"])
    raw = yaml.safe_load(Path("answers.yaml").read_text())
    raw["markers"] = {}
    Path("answers.yaml").write_text(yaml.safe_dump(raw))
    result = run_cli(["build"])
    assert (result.status, result.exit_code) == ("needs_decision", 0)
    assert not Path("archive/dwca.zip").exists()


def test_a_build_that_ends_in_error_exits_1_with_one_error_prefix_and_no_archive(run_cli):
    Path("conversion.yaml").write_text("steps: []\nraw_inputs: [absent.xlsx]\n")
    result = run_cli(["build", "--automatic"])
    assert (result.status, result.exit_code) == ("error", 1)
    lines = result.render().splitlines()
    assert lines[0].startswith("Error: ")
    assert not any(line.startswith(("error:", "Archive built at")) for line in lines)


def test_recording_an_audit_lists_its_findings_in_the_report_without_a_rebuild(run_cli):
    run_cli(["build"])
    Path("result.json").write_text(json.dumps({"findings": ["invented a depth"]}))
    result = run_cli(["audit", "record", "archive", "--from-file", "result.json"])
    assert result.exit_code == 0, result.render()
    report = Path("archive/CONVERSION_REPORT.md").read_text(encoding="utf-8")
    assert "invented a depth" in report
    assert "1 finding(s) recorded" in report
    html = Path("archive/CONVERSION_REPORT.html").read_text(encoding="utf-8")
    assert "invented a depth" in html
    assert Path("archive/reproduce/audit_record.json").exists()
    assert "evaluate" in (result.next_step or "")


def test_a_build_stopped_on_a_question_lists_the_proposals_it_already_wrote(run_cli):
    raw = yaml.safe_load(Path("answers.yaml").read_text())
    raw["markers"] = {}
    Path("answers.yaml").write_text(yaml.safe_dump(raw))
    result = run_cli(["build"])
    assert result.status == "needs_decision"
    review = Path("REVIEW.md").read_text(encoding="utf-8")
    waiting = review.split("## Waiting on you")[1].split("## ")[0]
    assert "proposed/control_roster.tsv" in waiting
    assert "proposed/taxa.tsv" in waiting
    assert "derived_values" in review.split("## Not reached yet")[1]


def test_a_build_that_runs_out_of_memory_leaves_no_half_written_archive(run_cli, monkeypatch):
    package = packaging._package

    def out_of_memory_once(*args, **kwargs):
        monkeypatch.setattr(packaging, "_package", package)
        Path("archive").mkdir(exist_ok=True)
        Path("archive/occurrence.txt").write_text("partial")
        raise ResourceLimitError("DuckDB ran out of memory")

    monkeypatch.setattr(packaging, "_package", out_of_memory_once)
    with pytest.raises(ResourceLimitError):
        run_cli(["build", "--automatic"])
    assert not Path("archive").exists()
    assert run_cli(["build", "--automatic"]).status == "ok"
