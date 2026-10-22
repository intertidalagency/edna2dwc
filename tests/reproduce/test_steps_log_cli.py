from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from edna2dwc.cli.common import UsageError


@pytest.fixture(autouse=True)
def config_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "conversion.yaml"
    path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")
    return path


def _record(run_cli, name="read_inputs.py", *, command=None, extra=()):
    script = Path(name)
    if not script.exists():
        script.write_text(f"print({name!r})\n", encoding="utf-8")
    return run_cli(
        [
            "record-step",
            "--config",
            "conversion.yaml",
            "--command",
            f"python scripts/{name}" if command is None else command,
            "--script",
            name,
            *extra,
        ]
    )


def _logged(config_path):
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def test_record_step_reports_the_step_it_recorded(run_cli, config_path):
    result = _record(run_cli, command="python scripts/read_inputs.py input/asv.csv --unit mg/L")
    assert result.render() == (
        "Recorded step 1, scripts/read_inputs.py, in conversion.yaml.\n"
        "Stage 3 of 5: Read\n"
        "Next: `edna2dwc assemble` on the tables the script writes"
    )


def test_record_step_position_counts_from_one(run_cli, config_path):
    _record(run_cli, "join.py")
    _record(run_cli, "fix.py")

    _record(run_cli, "export.py", extra=["--position", "1"])

    assert [s["script"] for s in _logged(config_path)["steps"]] == [
        "scripts/export.py",
        "scripts/join.py",
        "scripts/fix.py",
    ]


def test_recording_a_changed_script_again_says_it_replaced_the_step(run_cli):
    _record(run_cli, "join.py")
    Path("join.py").write_text("print('second')\n", encoding="utf-8")

    result = _record(run_cli, "join.py")

    assert result.text == (
        "Replaced step 1 in conversion.yaml: scripts/join.py was recorded there before, "
        "so the new copy and hash took its place."
    )


def test_record_step_records_each_raw_input_the_step_reads(run_cli, config_path):
    Path("plates.xlsx").write_text("x", encoding="utf-8")

    _record(
        run_cli,
        command="python scripts/read_inputs.py plates.xlsx",
        extra=["--raw", "plates.xlsx"],
    )

    assert _logged(config_path)["raw_inputs"] == ["plates.xlsx"]


@pytest.mark.parametrize(
    ("command", "extra", "message"),
    [
        (None, ["--position", "4"], "position 4 is outside a log of 0 step(s)"),
        (
            "python read_inputs.py",
            [],
            (
                "command never runs scripts/read_inputs.py, the copy of the script a replay has. "
                "Name that path in the command, as in python scripts/read_inputs.py"
            ),
        ),
        (
            'python scripts/read_inputs.py --note "unterminated',
            [],
            "command is not valid shell-quoted text: No closing quotation",
        ),
    ],
)
def test_record_step_refuses_a_step_it_cannot_log(run_cli, config_path, command, extra, message):
    with pytest.raises(UsageError) as error:
        _record(run_cli, command=command, extra=extra)
    assert str(error.value) == message
    assert "steps" not in _logged(config_path)


def test_record_step_refuses_a_raw_input_outside_the_conversion_directory(
    run_cli, config_path, tmp_path_factory
):
    outside = tmp_path_factory.mktemp("elsewhere") / "asv.csv"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(UsageError) as error:
        _record(
            run_cli,
            command=f"python scripts/read_inputs.py {outside}",
            extra=["--raw", str(outside)],
        )

    assert str(error.value).startswith(f"{outside} is outside the conversion directory")
    assert "steps" not in _logged(config_path)


@pytest.mark.parametrize(
    ("command", "script", "named"),
    [
        (
            "python scripts/read_inputs.py ../../testing/site/asv.csv",
            None,
            "../../testing/site/asv.csv",
        ),
        ("python scripts/read_inputs.py input/asv.csv", None, "input/asv.csv"),
        (None, "open('/work/input/data/asv.csv')\n", "/work/input/data/asv.csv"),
    ],
    ids=["above the conversion directory", "an input no --raw names", "a fixed place"],
)
def test_record_step_refuses_a_step_a_replay_could_not_run(
    run_cli, config_path, command, script, named
):
    Path("input").mkdir()
    Path("input/asv.csv").write_text("a\n", encoding="utf-8")
    if script is not None:
        Path("read_inputs.py").write_text(script, encoding="utf-8")

    with pytest.raises(UsageError) as error:
        _record(run_cli, command=command)

    assert named in str(error.value)
    assert "--raw" in str(error.value)
    assert "steps" not in _logged(config_path)


@pytest.mark.parametrize(
    ("command", "extra"),
    [
        ("python scripts/read_inputs.py --unit mg/L --url https://example.org/a", []),
        ("python scripts/read_inputs.py input/asv.csv", ["--raw", "input/asv.csv"]),
    ],
    ids=["values with slashes that name no file", "the raw input it records"],
)
def test_record_step_accepts_a_step_a_replay_can_run(run_cli, command, extra):
    Path("input").mkdir()
    Path("input/asv.csv").write_text("a\n", encoding="utf-8")

    result = _record(run_cli, command=command, extra=extra)

    assert result.exit_code == 0, result.render()
