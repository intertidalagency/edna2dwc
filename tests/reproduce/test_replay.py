from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from edna2dwc.reproduce import environment, replay, steps_log


@dataclass
class _FakeCompletedProcess:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _env() -> environment.EnvironmentRecord:
    return environment.EnvironmentRecord(
        edna2dwc_version="1.0.3",
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={"openpyxl": "3.1.2", "h5py": "3.11.0"},
    )


COMMANDS = ["python scripts/a.py raw/x.csv", "python scripts/b.py"]


def _steps() -> list[steps_log.Step]:
    return [
        steps_log.Step(
            n=1, command="python scripts/a.py raw/x.csv", script="scripts/a.py", sha256=""
        ),
        steps_log.Step(n=2, command="python scripts/b.py", script="scripts/b.py", sha256=""),
    ]


def test_build_uv_run_args_pins_every_dependency_but_not_edna2dwc_itself():
    assert replay.build_uv_run_args(_env(), "step1 && step2") == [
        "uv",
        "run",
        "--python",
        "3.12.4",
        "--with",
        "openpyxl==3.1.2",
        "--with",
        "h5py==3.11.0",
        "--",
        "sh",
        "-c",
        "step1 && step2",
    ]


def test_a_pinned_run_joins_every_step_into_one_script(tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _FakeCompletedProcess(returncode=0)

    replay.run_steps(tmp_path, ["python scripts/a.py", "true"], _env(), subprocess_run=fake_run)
    assert captured["args"][-1] == "python scripts/a.py && true"


@pytest.mark.parametrize(
    ("stderr", "culprit"),
    [
        ("error: no wheel found for openpyxl==3.1.2", "openpyxl"),
        ("something else entirely broke", None),
    ],
)
def test_a_pinned_run_that_cannot_resolve_names_the_culprit_it_can_identify(
    tmp_path, stderr, culprit
):
    def fake_run(args, **kwargs):
        return _FakeCompletedProcess(returncode=1, stderr=stderr)

    with pytest.raises(replay.EnvironmentUnavailableError) as exc_info:
        replay.run_steps(tmp_path, COMMANDS, _env(), subprocess_run=fake_run)
    assert str(exc_info.value) == stderr
    assert exc_info.value.culprit == culprit


def test_an_unpinned_run_joins_steps_with_no_uv_wrapping(tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _FakeCompletedProcess(returncode=0)

    replay.run_steps(tmp_path, COMMANDS, None, subprocess_run=fake_run)
    assert captured["args"][0] == "sh"
    assert captured["args"][-1] == " && ".join(COMMANDS)


@pytest.mark.parametrize(("culprit", "names_the_culprit"), [("openpyxl", True), (None, False)])
def test_unavailable_message_suggests_unpin_and_any_culprit_to_float(culprit, names_the_culprit):
    message = replay.unavailable_message(
        replay.EnvironmentUnavailableError("boom", culprit=culprit)
    )
    assert "--unpin" in message
    assert ("remove 'openpyxl' from conversion.yaml" in message) is names_the_culprit


def test_commands_for_replay_runs_build_after_every_recorded_step():
    assert replay.commands_for_replay(_steps()) == [
        "python scripts/a.py raw/x.csv",
        "python scripts/b.py",
        "edna2dwc build --automatic",
    ]


def test_missing_scripts_finds_a_step_with_no_vendored_file(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "a.py").write_text("pass\n", encoding="utf-8")
    assert replay.missing_scripts(tmp_path, _steps()) == ["scripts/b.py"]


def _bundle_with_answers(tmp_path: Path, answers: str) -> Path:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "answers.yaml").write_text(answers, encoding="utf-8")
    return bundle_dir


def test_default_archive_path_resolves_a_relative_out_dir_against_bundle_dir(tmp_path):
    bundle_dir = _bundle_with_answers(tmp_path, "out_dir: out\n")
    assert replay.default_archive_path(bundle_dir) == bundle_dir / "out" / "dwca.zip"


def test_the_shipped_archive_of_an_archives_own_bundle_is_the_zip_beside_it(tmp_path):
    bundle_dir = tmp_path / "archive" / "reproduce"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "answers.yaml").write_text("out_dir: archive\n", encoding="utf-8")
    assert replay.shipped_archive_path(bundle_dir) == tmp_path / "archive" / "dwca.zip"


def test_the_shipped_archive_of_a_conversion_directory_is_in_its_out_dir(tmp_path):
    bundle_dir = _bundle_with_answers(tmp_path, "out_dir: archive\n")
    assert replay.shipped_archive_path(bundle_dir) == bundle_dir / "archive" / "dwca.zip"


def test_default_archive_path_raises_without_a_recorded_out_dir(tmp_path):
    bundle_dir = _bundle_with_answers(tmp_path, "dataset_id: ds1\n")
    with pytest.raises(ValueError, match="out_dir"):
        replay.default_archive_path(bundle_dir)


def test_a_failing_step_is_not_reported_as_a_missing_package(tmp_path):
    scripts = []

    def fake_run(args, **kwargs):
        scripts.append(args[-1])
        if args[-1] == "true":
            return _FakeCompletedProcess(returncode=0)
        return _FakeCompletedProcess(returncode=1, stderr="could not parse row 4")

    result = replay.run_steps(tmp_path, COMMANDS, _env(), subprocess_run=fake_run)

    assert result.returncode == 1
    assert "row 4" in result.stderr
    assert scripts[0] == "true"


def _bundle(tmp_path) -> Path:
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "scripts").mkdir(parents=True)
    (bundle_dir / "conversion.yaml").write_text("build:\n  out_dir: out\n", encoding="utf-8")
    (bundle_dir / "scripts" / "reader.py").write_text("pass\n", encoding="utf-8")
    return bundle_dir


def _listing(directory: Path) -> list[str]:
    return sorted(str(path.relative_to(directory)) for path in directory.rglob("*"))


def test_copy_bundle_for_replay_carries_the_recipe_and_its_scripts(tmp_path):
    work_dir = replay.copy_bundle_for_replay(_bundle(tmp_path), tmp_path / "scratch")

    assert (work_dir / "conversion.yaml").read_text(encoding="utf-8") == (
        "build:\n  out_dir: out\n"
    )
    assert (work_dir / "scripts" / "reader.py").exists()


def test_copy_bundle_for_replay_leaves_the_shipped_bundle_alone(tmp_path):
    bundle_dir = _bundle(tmp_path)
    before = _listing(bundle_dir)

    replay.copy_bundle_for_replay(bundle_dir, tmp_path / "scratch")

    assert _listing(bundle_dir) == before


def test_copy_bundle_for_replay_refuses_a_scratch_directory_holding_anything(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "mine.tsv").write_text("keep me\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        replay.copy_bundle_for_replay(_bundle(tmp_path), scratch)

    assert (scratch / "mine.tsv").exists()


def test_copy_bundle_for_replay_refuses_a_scratch_path_that_is_a_file(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.write_text("keep me\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        replay.copy_bundle_for_replay(_bundle(tmp_path), scratch)

    assert scratch.read_text(encoding="utf-8") == "keep me\n"


def test_a_conversion_directory_replays_the_bundle_beside_its_archive(tmp_path):
    conversion_dir = _bundle_with_answers(tmp_path, "out_dir: archive\n")
    (conversion_dir / "archive" / "reproduce").mkdir(parents=True)
    assert replay.bundle_to_replay(conversion_dir) == conversion_dir / "archive" / "reproduce"


def test_a_bundle_directory_replays_itself(tmp_path):
    bundle_dir = tmp_path / "archive" / "reproduce"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "answers.yaml").write_text("out_dir: archive\n", encoding="utf-8")
    assert replay.bundle_to_replay(bundle_dir) == bundle_dir


def test_a_directory_without_answers_replays_itself(tmp_path):
    assert replay.bundle_to_replay(tmp_path) == tmp_path


def test_copy_bundle_for_replay_creates_the_tables_directory_the_scripts_write_into(tmp_path):
    work_dir = replay.copy_bundle_for_replay(_bundle(tmp_path), tmp_path / "scratch")

    assert (work_dir / "tables").is_dir()


def test_build_uv_run_args_skips_a_pin_whose_version_is_unknown():
    env = environment.EnvironmentRecord(
        edna2dwc_version="1.0.3",
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={"openpyxl": "3.1.2", "h5py": "unknown"},
    )

    args = replay.build_uv_run_args(env, "true")

    assert "h5py==unknown" not in args
    assert "openpyxl==3.1.2" in args
