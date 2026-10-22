import json

import pytest

from edna2dwc.cli import main
from edna2dwc.cli.run_log import LOG_ENV


def _run(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["edna2dwc", *argv])
    with pytest.raises(SystemExit) as exited:
        main()
    return exited.value.code


def _entries(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_without_the_env_nothing_is_logged(monkeypatch, tmp_path):
    monkeypatch.delenv(LOG_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    _run(monkeypatch, "doctor")
    assert list(tmp_path.iterdir()) == []


def test_a_command_appends_what_it_ran_and_how_it_ended(monkeypatch, tmp_path):
    log = tmp_path / "edna2dwc.jsonl"
    monkeypatch.setenv(LOG_ENV, str(log))
    _run(monkeypatch, "doctor")
    _run(monkeypatch, "doctor", "--json")

    first, second = _entries(log)
    assert first["argv"] == ["doctor"]
    assert second["argv"] == ["doctor", "--json"]
    assert first["command"] == "doctor"
    assert first["exit_code"] == 0
    assert first["seconds"] >= 0
    assert first["started"]
    assert first["version"]
    assert isinstance(first["findings"], list)
    assert first["requests"] == {}


def test_a_refused_command_logs_its_error(monkeypatch, tmp_path):
    log = tmp_path / "edna2dwc.jsonl"
    monkeypatch.setenv(LOG_ENV, str(log))
    monkeypatch.chdir(tmp_path)

    exit_code = _run(monkeypatch, "resolve-taxonomy")

    (entry,) = _entries(log)
    assert entry["exit_code"] == exit_code == 2
    assert "answers.yaml" in entry["error"]


def test_the_log_creates_its_missing_directory(monkeypatch, tmp_path):
    log = tmp_path / "missing" / "edna2dwc.jsonl"
    monkeypatch.setenv(LOG_ENV, str(log))

    assert _run(monkeypatch, "doctor") == 0
    (entry,) = _entries(log)
    assert entry["argv"] == ["doctor"]


def test_a_log_it_cannot_write_leaves_the_exit_code_alone(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(LOG_ENV, str(tmp_path))

    assert _run(monkeypatch, "doctor") == 0
    err = capsys.readouterr().err
    assert LOG_ENV in err
    assert "Traceback" not in err


def test_a_relative_log_path_stays_put_when_a_step_changes_directory(monkeypatch, tmp_path):
    start = tmp_path / "start"
    elsewhere = tmp_path / "elsewhere"
    start.mkdir()
    elsewhere.mkdir()
    monkeypatch.setenv(LOG_ENV, "edna2dwc.jsonl")
    monkeypatch.chdir(start)
    _run(monkeypatch, "doctor")
    monkeypatch.chdir(elsewhere)
    _run(monkeypatch, "doctor", "--json")

    assert len(_entries(start / "edna2dwc.jsonl")) == 2
    assert not (elsewhere / "edna2dwc.jsonl").exists()


def test_an_unhandled_exception_is_logged_as_a_crash(monkeypatch, tmp_path):
    log = tmp_path / "edna2dwc.jsonl"
    monkeypatch.setenv(LOG_ENV, str(log))

    def explode(*_args, **_kwargs):
        raise TypeError("expected str, not dict")

    monkeypatch.setattr("edna2dwc.cli.setup.installed_version", explode)
    with pytest.raises(TypeError):
        _run(monkeypatch, "doctor")

    (entry,) = _entries(log)
    assert entry["crashed"] is True
    assert entry["error"] == "TypeError: expected str, not dict"


def test_a_refused_command_is_not_a_crash(monkeypatch, tmp_path):
    log = tmp_path / "edna2dwc.jsonl"
    monkeypatch.setenv(LOG_ENV, str(log))
    monkeypatch.chdir(tmp_path)
    _run(monkeypatch, "resolve-taxonomy")
    (entry,) = _entries(log)
    assert "crashed" not in entry
