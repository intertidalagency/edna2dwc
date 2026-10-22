import os
import platform
import subprocess
import sys

import pytest

from edna2dwc.cli import app
from edna2dwc.common import progress, table
from edna2dwc.common.version import installed_version


@pytest.mark.parametrize(("ambient", "argv"), [(None, ["--quiet", "doctor"]), ("1", ["doctor"])])
def test_quiet_reaches_child_processes_from_the_flag_or_the_environment(
    monkeypatch, capsys, ambient, argv
):
    if ambient is None:
        monkeypatch.delenv(progress.QUIET_ENV, raising=False)
    else:
        monkeypatch.setenv(progress.QUIET_ENV, ambient)
    with pytest.raises(SystemExit):
        app.meta(argv, exit_on_error=False, print_error=False)
    assert os.environ.get(progress.QUIET_ENV) == "1"


def test_version_flag_prints_a_version(run_cli, capsys):
    run_cli(["--version"])
    assert installed_version() in capsys.readouterr().out


def test_no_command_shows_help(run_cli, capsys):
    run_cli([])
    assert "Usage" in capsys.readouterr().out


def _main(*args: str) -> list[str]:
    return [sys.executable, "-c", "from edna2dwc.cli.app import main; main()", *args]


def test_running_out_of_memory_ends_with_the_setting_to_change_not_a_traceback(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    rows = "".join(f"s{i}\tf{i}\t1\td__Bacteria\n" for i in range(50_000))
    path.write_text("sampleID\tfeatureID\tcount\ttaxonomy\n" + rows, encoding="utf-8")
    done = subprocess.run(
        _main("validate-intermediate", str(path)),
        env={**os.environ, table.MEMORY_LIMIT_ENV: "1MB"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1
    assert "Traceback" not in done.stderr
    assert done.stderr.startswith("Error: ")
    assert table.MEMORY_LIMIT_ENV in done.stderr


@pytest.mark.skipif(platform.system() == "Windows", reason="a closed pipe raises EINVAL there")
def test_output_piped_into_a_reader_that_stops_early_ends_without_a_traceback(tmp_path):
    long_text = tmp_path / "notes.md"
    long_text.write_text("a line of notes\n" * 50_000, encoding="utf-8")
    with subprocess.Popen(
        _main("text", str(long_text)), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as process:
        assert process.stdout is not None and process.stderr is not None
        process.stdout.readline()
        process.stdout.close()
        errors = process.stderr.read().decode()
    assert "Traceback" not in errors
    assert "BrokenPipeError" not in errors
