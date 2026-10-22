import json

from edna2dwc.cli import setup
from edna2dwc.cli.common import PACKAGE_DIR
from edna2dwc.common import table
from edna2dwc.reproduce.environment import READER_PACKAGES
from edna2dwc.validation import credentials


def test_doctor_reports_a_healthy_install_its_location_and_no_gbif_account(run_cli):
    result = run_cli(["doctor", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.render())
    assert payload["command"] == "doctor"
    assert payload["status"] == "ok"
    assert payload["location"] == str(PACKAGE_DIR)
    assert payload["packages"] == dict.fromkeys(READER_PACKAGES, True)
    assert payload["modules"] == dict.fromkeys(setup.SKILL_PATH_MODULES, True)
    assert payload["gbif_credentials"]["configured"] is False
    assert f"installed at {PACKAGE_DIR}" in result.text
    for name in READER_PACKAGES:
        assert name in result.text
    assert "credentials set --gbif" in result.text


def test_doctor_reports_the_memory_limit_and_the_free_disk_it_spills_to(run_cli, monkeypatch):
    monkeypatch.setenv(table.MEMORY_LIMIT_ENV, "3GB")
    result = run_cli(["doctor", "--json"])
    payload = json.loads(result.render())
    assert payload["memory_limit"] == "3GB"
    assert payload["spill_free_bytes"] > 0
    assert "memory limit  3GB" in result.text


def test_doctor_reports_an_error_when_nothing_imports(run_cli, monkeypatch):
    monkeypatch.setattr(setup, "_importable", lambda name: False)
    result = run_cli(["doctor", "--json"])
    payload = json.loads(result.render())
    assert result.exit_code == 1
    assert payload["status"] == "error"
    assert not any(payload["packages"].values())


def test_doctor_names_a_broken_module(run_cli, monkeypatch):
    missing = setup.SKILL_PATH_MODULES[0]
    monkeypatch.setattr(setup, "_importable", lambda name: name != missing)
    result = run_cli(["doctor"])
    assert result.exit_code == 1
    assert f"  {missing}  BROKEN" in result.render()


def test_doctor_reports_a_module_that_fails_to_import_for_any_reason(run_cli, monkeypatch):
    def explode(name):
        raise RuntimeError("half a file")

    monkeypatch.setattr(setup.importlib, "import_module", explode)
    payload = json.loads(run_cli(["doctor", "--json"]).render())
    assert not any(payload["modules"].values())


def test_doctor_reports_a_configured_gbif_account_without_its_password(run_cli, monkeypatch):
    monkeypatch.setenv(credentials.USER_ENV, "me")
    monkeypatch.setenv(credentials.PASS_ENV, "hunter2")
    result = run_cli(["doctor", "--json"])
    assert json.loads(result.render())["gbif_credentials"] == {
        "configured": True,
        "username": "me",
        "source": credentials.ENVIRONMENT,
    }
    assert "hunter2" not in result.render()
    assert "hunter2" not in result.text
