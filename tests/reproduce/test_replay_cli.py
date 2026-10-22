from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from edna2dwc.cli.common import CommandFailed, UsageError
from edna2dwc.reproduce import replay
from tests.archives import write_one_occurrence_archive

ENVIRONMENT = {
    "edna2dwc_version": "1.0.3",
    "python": "3.12.4",
    "pyproj": {"version": "3.6.1", "proj_data": "9.4.0"},
    "dependencies": {"openpyxl": "3.1.2"},
}


def _bundle(tmp_path, *, out_dir="out") -> Path:
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "scripts").mkdir(parents=True)
    (bundle_dir / "scripts" / "read.py").write_text("pass\n", encoding="utf-8")
    (bundle_dir / "answers.yaml").write_text(
        yaml.safe_dump({"dataset_id": "ds1", "out_dir": out_dir}), encoding="utf-8"
    )
    (bundle_dir / "conversion.yaml").write_text(
        yaml.safe_dump(
            {
                "environment": ENVIRONMENT,
                "steps": [{"n": 1, "command": "true", "script": "scripts/read.py", "sha256": ""}],
            }
        ),
        encoding="utf-8",
    )
    return bundle_dir


def _halt(code: str, message: str) -> list[dict]:
    return [{"code": code, "severity": "error", "message": message, "count": 1}]


def _rebuild_with(monkeypatch, *, returncode=0, stderr="", findings=(), effect=None):
    seen = {}

    def run_steps(work_dir, *args, **kwargs):
        seen["work_dir"] = Path(work_dir)
        if effect is not None:
            effect(Path(work_dir))
        if findings is not None:
            (Path(work_dir) / "findings.json").write_text(json.dumps(list(findings)))
        return subprocess.CompletedProcess([], returncode, stdout="rebuilt", stderr=stderr)

    monkeypatch.setattr(replay, "run_steps", run_steps)
    return seen


@pytest.fixture
def checked_bundle(tmp_path):
    out_dir = tmp_path / "out"
    write_one_occurrence_archive(out_dir)
    return _bundle(tmp_path, out_dir=str(out_dir)), out_dir / "dwca.zip"


def test_replay_dry_run_prints_every_command_it_would_run(run_cli, tmp_path):
    result = run_cli(["replay", str(_bundle(tmp_path)), "--dry-run"])
    assert result.render().splitlines() == ["true", "edna2dwc build --automatic"]


def test_replay_requires_a_recorded_environment(run_cli, tmp_path):
    config_path = tmp_path / "conversion.yaml"
    config_path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")
    with pytest.raises(UsageError) as error:
        run_cli(["replay", str(tmp_path)])
    assert str(error.value) == f"{config_path} has no recorded environment to replay against"


def test_replay_fails_when_a_vendored_script_is_gone(run_cli, tmp_path):
    bundle_dir = _bundle(tmp_path)
    (bundle_dir / "scripts" / "read.py").unlink()
    with pytest.raises(CommandFailed) as error:
        run_cli(["replay", str(bundle_dir)])
    assert str(error.value) == f"SCRIPT_MISSING: scripts/read.py is absent from {bundle_dir}"


def test_replay_without_compare_rejects_two_targets(run_cli, tmp_path):
    (tmp_path / "other_dir").mkdir()
    with pytest.raises(UsageError) as error:
        run_cli(["replay", str(_bundle(tmp_path)), str(tmp_path / "other_dir")])
    assert str(error.value) == "replay takes exactly one bundle directory (see --compare)"


@pytest.mark.parametrize(
    ("returncode", "findings", "stderr", "exit_code", "status"),
    [
        (0, [], "", 0, "ok"),
        (
            0,
            _halt("PROPOSAL_OPEN", "metadata.license: pending"),
            "",
            0,
            "needs_review: metadata.license: pending",
        ),
        (
            0,
            _halt("DECISION_REQUIRED", "markers.16S"),
            "",
            1,
            "needs_decision: markers.16S",
        ),
        (
            1,
            _halt("RUN_FAILED", "the archive failed validation"),
            "",
            1,
            "error: the archive failed validation",
        ),
        (1, None, "a real step failed", 1, "error: a real step failed"),
        (1, None, "", 1, "error: the replayed steps failed"),
    ],
)
def test_replay_prints_the_rebuild_status_last(
    run_cli, tmp_path, monkeypatch, returncode, findings, stderr, exit_code, status
):
    _rebuild_with(monkeypatch, returncode=returncode, findings=findings, stderr=stderr)
    result = run_cli(["replay", str(_bundle(tmp_path))])
    assert result.exit_code == exit_code
    assert result.text.splitlines()[-1] == f"Rebuild status: {status}"


def test_replay_suggests_unpin_when_the_recorded_environment_is_unavailable(
    run_cli, tmp_path, monkeypatch
):
    unavailable = replay.EnvironmentUnavailableError("no wheel for openpyxl", culprit="openpyxl")

    def run_steps(*args, **kwargs):
        raise unavailable

    monkeypatch.setattr(replay, "run_steps", run_steps)
    with pytest.raises(CommandFailed) as error:
        run_cli(["replay", str(_bundle(tmp_path))])
    assert str(error.value) == replay.unavailable_message(unavailable)


def test_replay_unpin_prints_the_version_table_and_replays_in_the_scratch_dir(
    run_cli, capsys, tmp_path, monkeypatch
):
    bundle_dir = _bundle(tmp_path)
    scratch = tmp_path / "scratch"
    seen = _rebuild_with(monkeypatch)

    run_cli(["replay", str(bundle_dir), "--unpin", "--scratch-dir", str(scratch)])

    printed = capsys.readouterr().out
    assert "openpyxl: recorded 3.1.2, current " in printed
    assert (
        f"Replaying a copy of {bundle_dir} in {scratch}; the bundle itself is only read.\n"
        in printed
    )
    assert seen["work_dir"] == scratch


def test_replay_refuses_a_scratch_directory_that_already_holds_something(run_cli, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "mine.tsv").write_text("keep me\n", encoding="utf-8")

    with pytest.raises(UsageError) as error:
        run_cli(["replay", str(_bundle(tmp_path)), "--unpin", "--scratch-dir", str(scratch)])

    assert str(error.value) == (
        f"{scratch} is not empty. Point --scratch-dir at an empty or absent directory"
    )


def test_replay_check_passes_when_the_rebuild_matches_the_shipped_archive(
    run_cli, capsys, checked_bundle, monkeypatch
):
    bundle_dir, shipped = checked_bundle
    _rebuild_with(monkeypatch)

    result = run_cli(["replay", str(bundle_dir), "--check"])

    assert result.exit_code == 0
    assert result.text == (
        "# Archive comparison\n\nNo differences.\n"
        f"Wrote {shipped.parent / 'comparison_summary.md'}.\nRebuild status: ok"
    )
    assert (
        f"Replaying a copy of {bundle_dir}; the bundle itself is only read.\n"
        in capsys.readouterr().out
    )


def test_replay_check_run_inside_an_archives_bundle_writes_its_summary_beside_the_archive(
    run_cli, tmp_path, monkeypatch
):
    shipped = write_one_occurrence_archive(tmp_path / "archive")
    reproduce = shutil.move(
        _bundle(tmp_path, out_dir="archive"), tmp_path / "archive" / "reproduce"
    )

    def rebuild(work_dir):
        (work_dir / "archive").mkdir()
        shutil.copyfile(shipped, work_dir / "archive" / "dwca.zip")

    _rebuild_with(monkeypatch, effect=rebuild)
    monkeypatch.chdir(reproduce)
    result = run_cli(["replay", ".", "--check"])

    summary = tmp_path / "archive" / "comparison_summary.md"
    assert result.exit_code == 0, result.render()
    assert summary.read_text(encoding="utf-8") == "# Archive comparison\n\nNo differences.\n"
    assert not list(Path(reproduce).glob("comparison_summary.*"))


def test_replay_check_restores_the_shipped_archive_and_prints_the_error_when_the_rebuild_fails(
    run_cli, checked_bundle, monkeypatch
):
    bundle_dir, shipped = checked_bundle
    original_bytes = shipped.read_bytes()

    def truncate(_work_dir):
        shipped.write_bytes(b"not a real zip, simulating a truncated write")

    _rebuild_with(monkeypatch, returncode=1, stderr="step failed", findings=None, effect=truncate)
    result = run_cli(["replay", str(bundle_dir), "--check"])

    assert result.exit_code == 1
    assert result.text.splitlines()[-1] == "Rebuild status: error: step failed"
    assert shipped.read_bytes() == original_bytes


def test_replay_check_fails_when_the_rebuild_diverges_from_the_shipped_archive(
    run_cli, checked_bundle, monkeypatch
):
    bundle_dir, shipped = checked_bundle
    original_bytes = shipped.read_bytes()
    _rebuild_with(monkeypatch, effect=lambda _: write_one_occurrence_archive(shipped.parent, "B"))

    with pytest.raises(CommandFailed) as error:
        run_cli(["replay", str(bundle_dir), "--check"])

    summary = shipped.parent / "comparison_summary.md"
    assert str(error.value) == f"Archives diverge: see {summary}."
    assert "scientificName" in summary.read_text(encoding="utf-8")
    assert shipped.read_bytes() == original_bytes


def test_replay_check_restores_the_shipped_archive_when_the_rebuild_never_writes_one(
    run_cli, checked_bundle, monkeypatch
):
    bundle_dir, shipped = checked_bundle
    original_bytes = shipped.read_bytes()
    _rebuild_with(monkeypatch, effect=lambda _: shipped.unlink())

    with pytest.raises(CommandFailed) as error:
        run_cli(["replay", str(bundle_dir), "--check"])

    assert str(error.value) == f"replay finished but did not write {shipped}"
    assert shipped.read_bytes() == original_bytes


def test_replay_check_against_another_archive_still_protects_the_bundles_own(
    run_cli, checked_bundle, monkeypatch, tmp_path
):
    bundle_dir, own_zip = checked_bundle
    own_bytes = own_zip.read_bytes()
    reference_zip = write_one_occurrence_archive(tmp_path / "reference", "Reference")
    reference_bytes = reference_zip.read_bytes()
    _rebuild_with(
        monkeypatch, effect=lambda _: write_one_occurrence_archive(own_zip.parent, "Rebuilt")
    )

    with pytest.raises(CommandFailed) as error:
        run_cli(["replay", str(bundle_dir), "--check", "--against", str(reference_zip)])

    assert (
        str(error.value)
        == f"Archives diverge: see {reference_zip.parent / 'comparison_summary.md'}."
    )
    assert own_zip.read_bytes() == own_bytes
    assert reference_zip.read_bytes() == reference_bytes


def test_replay_check_requires_a_shipped_archive_when_none_is_recorded(run_cli, tmp_path):
    nowhere = tmp_path / "nowhere"
    with pytest.raises(UsageError) as error:
        run_cli(["replay", str(_bundle(tmp_path, out_dir=str(nowhere))), "--check"])
    assert str(error.value) == f"{nowhere / 'dwca.zip'} does not exist. Pass --against"


def test_replay_check_deletes_the_temporary_copy_it_replayed_in(
    run_cli, checked_bundle, monkeypatch
):
    bundle_dir, _shipped = checked_bundle
    seen = _rebuild_with(monkeypatch)

    run_cli(["replay", str(bundle_dir), "--check"])

    assert not seen["work_dir"].is_relative_to(bundle_dir)
    assert not seen["work_dir"].exists()


def test_replay_check_replays_in_the_scratch_dir_it_is_given_and_keeps_it(
    run_cli, checked_bundle, monkeypatch, tmp_path
):
    bundle_dir, _shipped = checked_bundle
    scratch = tmp_path / "beside_raw_inputs"
    seen = _rebuild_with(monkeypatch)

    result = run_cli(["replay", str(bundle_dir), "--check", "--scratch-dir", str(scratch)])

    assert result.exit_code == 0, result.render()
    assert seen["work_dir"] == scratch
    assert (scratch / "conversion.yaml").exists()


def test_replay_unpin_runs_the_steps_under_the_current_environment(run_cli, tmp_path, monkeypatch):
    seen = {}

    def run_steps(work_dir, commands, env, **kwargs):
        seen["env"] = env
        (Path(work_dir) / "findings.json").write_text("[]")
        return subprocess.CompletedProcess([], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(replay, "run_steps", run_steps)
    run_cli(["replay", str(_bundle(tmp_path)), "--unpin"])

    assert seen["env"].edna2dwc_version != ENVIRONMENT["edna2dwc_version"]


def test_replay_json_reports_the_rebuild_status_when_no_archive_is_compared(
    run_cli, tmp_path, monkeypatch
):
    _rebuild_with(
        monkeypatch, returncode=1, findings=_halt("RUN_FAILED", "the archive failed validation")
    )
    result = run_cli(["replay", str(_bundle(tmp_path)), "--json"])
    assert json.loads(result.render())["rebuild_status"] == "error: the archive failed validation"


def test_replay_reads_the_status_of_this_rebuild_not_of_an_earlier_build(
    run_cli, tmp_path, monkeypatch
):
    bundle_dir = _bundle(tmp_path)
    (bundle_dir / "findings.json").write_text("[]")
    _rebuild_with(monkeypatch, returncode=1, stderr="a real step failed", findings=None)
    result = run_cli(["replay", str(bundle_dir)])
    assert result.text.splitlines()[-1] == "Rebuild status: error: a real step failed"
