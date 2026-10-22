from __future__ import annotations

import json
from pathlib import Path

from cyclopts import CycloptsError
import pytest

from edna2dwc.cli.common import CommandLineError
from edna2dwc.review.audit import build_audit_prompt, load_recorded_audit


def test_audit_prompt_requires_source(run_cli, tmp_path):
    with pytest.raises(CycloptsError):
        run_cli(["audit", "prompt", str(tmp_path)])


def test_audit_prompt_emits_the_full_text(run_cli, tmp_path):
    result = run_cli(["audit", "prompt", str(tmp_path), "--source", "raw.csv"])
    assert result.exit_code == 0, result.render()
    assert (
        build_audit_prompt(source_paths=["raw.csv"], archive_dir=str(tmp_path)) in result.render()
    )


@pytest.mark.parametrize(
    ("findings", "said"), [([], "0 audit finding(s)"), (["bad row"], "1 audit finding")]
)
def test_audit_record_writes_the_findings(run_cli, tmp_path, monkeypatch, findings, said):
    monkeypatch.chdir(tmp_path)
    from_file = tmp_path / "audit_result.json"
    from_file.write_text(json.dumps({"findings": findings}), encoding="utf-8")
    result = run_cli(["audit", "record", str(tmp_path), "--from-file", str(from_file)])
    assert result.exit_code == 0, result.render()
    assert said in result.render()
    assert load_recorded_audit(Path("audit_record.json")) == (findings, True)


def test_audit_record_writes_the_record_beside_answers_yaml_not_in_the_archive(
    run_cli, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    from_file = tmp_path / "audit_result.json"
    from_file.write_text(json.dumps({"findings": []}), encoding="utf-8")
    run_cli(["audit", "record", "archive", "--from-file", str(from_file)])
    assert (tmp_path / "audit_record.json").exists()
    assert not (archive_dir / "audit_record.json").exists()


def test_audit_record_rejects_a_malformed_result_file(run_cli, tmp_path):
    from_file = tmp_path / "audit_result.json"
    from_file.write_text(json.dumps({"findings": "bad row"}), encoding="utf-8")
    with pytest.raises(CommandLineError) as error:
        run_cli(["audit", "record", str(tmp_path), "--from-file", str(from_file)])
    assert "'findings' must be a list of strings" in str(error.value)
