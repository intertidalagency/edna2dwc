from __future__ import annotations

import ntpath
import os
from pathlib import Path

import pytest
import yaml

from edna2dwc.reproduce import steps_log


@pytest.fixture
def conversion_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _insert(name: str = "read.py", *, command: str | None = None, index: int | None = None):
    script = Path(name)
    if not script.exists():
        script.write_text(f"print({name!r})\n", encoding="utf-8")
    return steps_log.insert_step(
        Path("conversion.yaml"),
        command=f"python scripts/{name}" if command is None else command,
        script=script,
        index=index,
    )


def test_a_recorded_command_does_not_carry_an_inline_password_into_the_log(conversion_dir):
    step = _insert(command="GBIF_USER=me GBIF_PASS=hunter2 python scripts/read.py")
    assert step.command == "GBIF_USER=me python scripts/read.py"
    assert "hunter2" not in (conversion_dir / "conversion.yaml").read_text(encoding="utf-8")


def test_a_secret_assignment_is_dropped_rather_than_replaced_so_replay_falls_through():
    redacted = steps_log.redact_command("EDNA2DWC_GBIF_PASS=hunter2 edna2dwc validate x --gbif")
    assert redacted == "edna2dwc validate x --gbif"


@pytest.mark.parametrize(
    "assignment",
    [
        "API_TOKEN=t",
        "DB_PASSWORD=p",
        "CLIENT_SECRET=s",
        "GBIF_PASSWD=p",
        "API_KEY=k",
        "APIKEY=k",
        "AWS_SECRET_ACCESS_KEY=k",
        "credentials=c",
        "pass=p",
    ],
)
def test_redaction_covers_every_secret_named_variable(assignment):
    assert steps_log.redact_command(f"{assignment} edna2dwc validate x") == "edna2dwc validate x"


@pytest.mark.parametrize(
    "command",
    [
        "compass=north python scripts/read.py",
        "KEYBOARD=us python scripts/read.py",
        "python scripts/read.py --password=abc",
        "python scripts/read.py --title 'my dataset' --out archive/",
    ],
)
def test_a_command_with_nothing_to_redact_is_recorded_byte_for_byte(command, conversion_dir):
    assert _insert(command=command).command == command


def test_load_steps_is_empty_without_a_file_or_a_steps_key(tmp_path):
    path = tmp_path / "conversion.yaml"
    assert steps_log.load_steps(path) == []
    path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")
    assert steps_log.load_steps(path) == []


def test_insert_step_creates_the_file_when_it_does_not_exist(conversion_dir):
    step = _insert()
    assert step.n == 1
    assert steps_log.load_steps(conversion_dir / "conversion.yaml") == [step]


def test_insert_step_preserves_existing_fields(conversion_dir):
    path = conversion_dir / "conversion.yaml"
    path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")
    _insert()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["dataset_id"] == "ds1"
    assert len(raw["steps"]) == 1


def test_insert_step_numbers_sequentially(conversion_dir):
    first, second = _insert("a.py"), _insert("b.py")
    assert (first.n, second.n) == (1, 2)
    assert [s.script for s in steps_log.load_steps(conversion_dir / "conversion.yaml")] == [
        "scripts/a.py",
        "scripts/b.py",
    ]


def test_insert_step_rejects_a_command_with_unbalanced_quoting(conversion_dir):
    with pytest.raises(ValueError):
        _insert(command='python scripts/read.py --note "unterminated')


def test_insert_step_vendors_and_hashes_the_script(conversion_dir):
    script = conversion_dir / "patch.py"
    script.write_bytes(b"print('hello')\n")

    step = _insert("patch.py")

    assert step.script == "scripts/patch.py"
    assert (conversion_dir / "scripts" / "patch.py").read_text() == "print('hello')\n"
    assert step.sha256 == steps_log.hash_bytes(b"print('hello')\n")


def test_insert_step_puts_the_entry_at_the_given_index(conversion_dir):
    _insert("a.py")
    _insert("b.py")

    step = _insert("first.py", index=0)

    steps = steps_log.load_steps(conversion_dir / "conversion.yaml")
    assert step.n == 1
    assert [s.script for s in steps] == ["scripts/first.py", "scripts/a.py", "scripts/b.py"]
    assert [s.n for s in steps] == [1, 2, 3]


def test_insert_step_rejects_an_index_past_the_end(conversion_dir):
    _insert("a.py")

    with pytest.raises(ValueError, match="position 8"):
        _insert("b.py", index=7)


def test_record_raw_inputs_appends_each_path_once(tmp_path):
    path = tmp_path / "conversion.yaml"
    path.write_text(yaml.safe_dump({"raw_inputs": ["data/a.xlsx"]}), encoding="utf-8")

    steps_log.record_raw_inputs(path, (Path("data/a.xlsx"), Path("data/b.biom")))

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["raw_inputs"] == ["data/a.xlsx", "data/b.biom"]


def test_record_raw_inputs_with_no_paths_leaves_the_file_alone(tmp_path):
    path = tmp_path / "conversion.yaml"
    path.write_text("steps: []\n", encoding="utf-8")

    steps_log.record_raw_inputs(path, ())

    assert path.read_text(encoding="utf-8") == "steps: []\n"


def test_vendor_script_copies_verbatim_content(tmp_path):
    script = tmp_path / "src" / "reader.py"
    script.parent.mkdir()
    script.write_bytes(b"x = 1\n")
    scripts_dir = tmp_path / "scripts"

    dest, sha256 = steps_log.vendor_script(script, scripts_dir)

    assert dest == scripts_dir / "reader.py"
    assert dest.read_text() == "x = 1\n"
    assert sha256 == steps_log.hash_bytes(b"x = 1\n")


def test_vendor_script_re_vendoring_the_identical_script_is_a_noop(tmp_path):
    script = tmp_path / "reader.py"
    script.write_bytes(b"x = 1\n")
    scripts_dir = tmp_path / "scripts"
    steps_log.vendor_script(script, scripts_dir)

    dest, sha256 = steps_log.vendor_script(script, scripts_dir)
    assert dest.read_text() == "x = 1\n"
    assert sha256 == steps_log.hash_bytes(b"x = 1\n")


def test_vendor_script_refuses_to_overwrite_a_different_script_under_the_same_name(tmp_path):
    scripts_dir = tmp_path / "scripts"
    first = tmp_path / "one" / "reader.py"
    first.parent.mkdir()
    first.write_text("x = 1\n", encoding="utf-8")
    steps_log.vendor_script(first, scripts_dir)

    second = tmp_path / "two" / "reader.py"
    second.parent.mkdir()
    second.write_text("x = 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="reader.py"):
        steps_log.vendor_script(second, scripts_dir)
    assert (scripts_dir / "reader.py").read_text() == "x = 1\n"


@pytest.mark.parametrize("command", ["", "   ", "\t\n"])
def test_insert_step_refuses_a_command_with_nothing_to_run(command, conversion_dir):
    with pytest.raises(ValueError, match="command"):
        _insert(command=command)
    assert steps_log.load_steps(conversion_dir / "conversion.yaml") == []


@pytest.mark.parametrize("command", ["python patch.py", "python scripts/other.py", "true"])
def test_insert_step_refuses_a_command_that_never_runs_its_vendored_script(
    command, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "patch.py"
    script.write_bytes(b"print('hello')\n")
    with pytest.raises(ValueError, match="scripts/patch.py"):
        steps_log.insert_step(tmp_path / "conversion.yaml", command=command, script=script)
    assert steps_log.load_steps(tmp_path / "conversion.yaml") == []


@pytest.mark.parametrize(
    "command",
    [
        "python scripts/patch.py -o occurrence_long.tsv",
        "python ./scripts/patch.py",
        "uv run --script=scripts/patch.py",
    ],
)
def test_insert_step_accepts_a_command_that_runs_its_vendored_script(
    command, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "patch.py"
    script.write_bytes(b"print('hello')\n")
    step = steps_log.insert_step(tmp_path / "conversion.yaml", command=command, script=script)
    assert step.command == command


def test_insert_step_accepts_a_vendored_script_where_paths_use_backslashes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, "path", ntpath)
    script = tmp_path / "patch.py"
    script.write_bytes(b"print('hello')\n")
    step = steps_log.insert_step(
        tmp_path / "conversion.yaml",
        command="python scripts/patch.py",
        script=script,
    )
    assert step.script == "scripts/patch.py"


def test_a_script_recorded_after_assemble_goes_before_it(conversion_dir):
    _insert("read.py")
    steps_log.record_tool_step(Path("conversion.yaml"), "edna2dwc assemble --counts t.csv")
    _insert("fix.py")
    steps = steps_log.load_steps(conversion_dir / "conversion.yaml")
    assert [s.command for s in steps] == [
        "python scripts/read.py",
        "python scripts/fix.py",
        "edna2dwc assemble --counts t.csv",
    ]


def test_recording_assemble_again_replaces_its_step(conversion_dir):
    path = Path("conversion.yaml")
    steps_log.record_tool_step(path, "edna2dwc assemble --counts a.csv")
    steps_log.record_tool_step(path, "edna2dwc assemble --counts b.csv")
    assert [s.command for s in steps_log.load_steps(path)] == ["edna2dwc assemble --counts b.csv"]


def test_a_raw_input_outside_the_conversion_says_to_keep_raw(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-elsewhere.csv"
    outside.write_text("a\n")
    with pytest.raises(ValueError, match="Keep --raw") as refused:
        steps_log.refuse_raw_inputs_outside(tmp_path, (outside,))
    assert "--raw" in str(refused.value)
