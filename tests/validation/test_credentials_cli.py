from __future__ import annotations

import json

from cyclopts import CycloptsError
import httpx
from keyring import set_keyring
import pytest

from edna2dwc.cli import setup as credentials_cli
from edna2dwc.cli.common import CommandFailed, UsageError
from edna2dwc.validation import credentials
from tests.validation.test_credentials import FakeKeyring


@pytest.fixture
def keyring() -> FakeKeyring:
    store = FakeKeyring()
    set_keyring(store)
    return store


@pytest.fixture
def at_a_terminal(monkeypatch) -> None:
    monkeypatch.setattr(credentials_cli.sys.stdin, "isatty", lambda: True)


@pytest.fixture
def typed_password(monkeypatch) -> None:
    monkeypatch.setattr(credentials_cli.getpass, "getpass", lambda prompt: "hunter2")


@pytest.fixture
def gbif_accepts(monkeypatch) -> None:
    monkeypatch.setattr(credentials_cli, "credentials_accepted", lambda creds: True)


def test_set_stores_the_account_the_prompt_supplied(
    run_cli, keyring, at_a_terminal, typed_password, gbif_accepts
):
    result = run_cli(["credentials", "set", "--gbif", "--username", "me"])
    assert result.exit_code == 0, result.render()
    assert keyring.stored == {(credentials.SERVICE, "me"): "hunter2"}


def test_set_never_prints_the_password_it_stored(
    run_cli, keyring, at_a_terminal, typed_password, gbif_accepts
):
    result = run_cli(["credentials", "set", "--gbif", "--username", "me", "--json"])
    assert "hunter2" not in result.render()
    assert json.loads(result.render())["verified"] is True


def test_set_refuses_to_prompt_where_there_is_no_terminal(run_cli, keyring, monkeypatch):
    monkeypatch.setattr(credentials_cli.sys.stdin, "isatty", lambda: False)
    with pytest.raises(UsageError):
        run_cli(["credentials", "set", "--gbif", "--username", "me"])
    assert keyring.stored == {}


def test_set_stores_nothing_when_gbif_rejects_the_account(
    run_cli, keyring, at_a_terminal, typed_password, monkeypatch
):
    monkeypatch.setattr(credentials_cli, "credentials_accepted", lambda creds: False)
    with pytest.raises(CommandFailed, match="401"):
        run_cli(["credentials", "set", "--gbif", "--username", "me"])
    assert keyring.stored == {}
    assert not credentials.config_path().exists()


def test_set_says_how_to_store_an_account_it_could_not_check(
    run_cli, keyring, at_a_terminal, typed_password, monkeypatch
):
    def unreachable(creds):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(credentials_cli, "credentials_accepted", unreachable)
    with pytest.raises(CommandFailed, match="--no-verify"):
        run_cli(["credentials", "set", "--gbif", "--username", "me"])


def test_set_with_no_verify_stores_without_asking_gbif(
    run_cli, keyring, at_a_terminal, typed_password
):
    result = run_cli(["credentials", "set", "--gbif", "--username", "me", "--no-verify", "--json"])
    assert result.exit_code == 0, result.render()
    assert keyring.stored == {(credentials.SERVICE, "me"): "hunter2"}
    assert json.loads(result.render())["verified"] is False


def test_every_credentials_command_needs_the_gbif_flag(run_cli):
    with pytest.raises(UsageError, match="--gbif"):
        run_cli(["credentials", "set"])
    with pytest.raises(UsageError, match="--gbif"):
        run_cli(["credentials", "clear"])


def test_there_is_no_flag_that_takes_a_password(run_cli, keyring, at_a_terminal, typed_password):
    with pytest.raises(CycloptsError):
        run_cli(["credentials", "set", "--gbif", "--password", "hunter2"])


def test_show_names_every_place_it_looked(run_cli):
    result = run_cli(["credentials", "show"])
    rendered = result.render()
    assert credentials.USER_ENV in rendered
    assert str(credentials.config_path()) in rendered
    assert credentials.GBIF_HOST in rendered


def test_show_reports_a_stored_account_without_reading_the_keyring(run_cli, keyring, monkeypatch):
    credentials.store_gbif("me", "hunter2")
    monkeypatch.setattr(keyring, "get_password", lambda *key: pytest.fail("read the keyring"))
    result = run_cli(["credentials", "show", "--json"])
    payload = json.loads(result.render())
    assert payload["gbif"] == {
        "configured": True,
        "username": "me",
        "source": credentials.KEYRING_UNREAD,
        "code": None,
        "detail": None,
    }
    assert "hunter2" not in result.render()


def test_show_reports_the_finding_code_for_a_half_configured_machine(run_cli, monkeypatch):
    monkeypatch.setenv(credentials.USER_ENV, "me")
    payload = json.loads(run_cli(["credentials", "show", "--json"]).render())
    assert payload["gbif"]["code"] == credentials.PARTIAL


def test_clear_removes_what_set_stored(run_cli, keyring):
    credentials.store_gbif("me", "hunter2")
    result = run_cli(["credentials", "clear", "--gbif"])
    assert result.exit_code == 0, result.render()
    assert keyring.stored == {}
    assert not credentials.config_path().exists()


def test_clear_reports_an_account_in_the_environment_it_cannot_remove(
    run_cli, keyring, monkeypatch
):
    monkeypatch.setenv(credentials.USER_ENV, "me")
    monkeypatch.setenv(credentials.PASS_ENV, "hunter2")
    result = run_cli(["credentials", "clear", "--gbif", "--json"])
    assert json.loads(result.render())["still_configured_in"] == credentials.ENVIRONMENT


def test_clear_says_when_a_keyring_entry_was_left_behind(run_cli, keyring):
    credentials.store_gbif("me", "hunter2")
    credentials.config_path().write_text("gbif: [unclosed\n", encoding="utf-8")
    payload = json.loads(run_cli(["credentials", "clear", "--gbif", "--json"]).render())
    assert payload["cleared"] == [credentials.CONFIG_FILE]
    assert "keyring" in payload["left_behind"]
    assert "hunter2" not in payload["left_behind"]


def test_doctor_names_a_stored_account_without_reading_the_keyring(run_cli, keyring, monkeypatch):
    credentials.store_gbif("me", "hunter2")
    reads = []
    monkeypatch.setattr(keyring, "get_password", lambda *key: reads.append(key))

    result = run_cli(["doctor", "--json"])

    assert reads == []
    assert json.loads(result.render())["gbif_credentials"] == {
        "configured": True,
        "username": "me",
        "source": credentials.KEYRING_UNREAD,
    }


def test_show_does_not_credit_the_file_when_the_keyring_may_hold_the_password(
    run_cli, keyring, monkeypatch
):
    credentials.store_gbif("me", "from-keyring")
    credentials._write_settings({"username": "me", "password": "from-file"})
    used = credentials.gbif_credentials()
    assert isinstance(used, credentials.Credentials)
    assert used.source == credentials.KEYRING
    monkeypatch.setattr(keyring, "get_password", lambda *key: pytest.fail("read the keyring"))
    payload = json.loads(run_cli(["credentials", "show", "--json"]).render())
    assert payload["gbif"]["source"] == credentials.KEYRING_OR_FILE_UNREAD
