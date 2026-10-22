from __future__ import annotations

import platform
import stat

from keyring import set_keyring
from keyring.backend import KeyringBackend
import pytest

from edna2dwc.validation import credentials


class FakeKeyring(KeyringBackend):
    def __init__(self) -> None:
        super().__init__()
        self.stored: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.stored.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.stored[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        del self.stored[(service, username)]


@pytest.fixture
def keyring() -> FakeKeyring:
    store = FakeKeyring()
    set_keyring(store)
    return store


def unusable() -> credentials.Unavailable:
    lookup = credentials.gbif_credentials()
    assert isinstance(lookup, credentials.Unavailable), lookup
    return lookup


def test_nothing_configured_reports_missing_and_names_the_command():
    lookup = unusable()
    assert lookup.code == credentials.MISSING
    assert "credentials set --gbif" in lookup.detail


def test_both_environment_variables_win_over_everything_else(monkeypatch, keyring):
    credentials.store_gbif("stored-user", "stored-pass")
    monkeypatch.setenv(credentials.USER_ENV, "env-user")
    monkeypatch.setenv(credentials.PASS_ENV, "env-pass")
    assert credentials.gbif_credentials() == credentials.Credentials(
        username="env-user", password="env-pass", source=credentials.ENVIRONMENT
    )


def test_a_username_with_no_password_is_reported_as_partial_not_as_absent(monkeypatch):
    monkeypatch.setenv(credentials.USER_ENV, "me")
    lookup = unusable()
    assert lookup.code == credentials.PARTIAL
    assert credentials.PASS_ENV in lookup.detail


def test_a_password_with_no_username_is_reported_as_partial(monkeypatch):
    monkeypatch.setenv(credentials.PASS_ENV, "hunter2")
    lookup = unusable()
    assert lookup.code == credentials.PARTIAL
    assert credentials.USER_ENV in lookup.detail
    assert "hunter2" not in lookup.detail


def test_the_keyring_holds_the_password_and_the_file_holds_only_the_username(keyring):
    assert credentials.store_gbif("me", "hunter2") == credentials.KEYRING
    assert "hunter2" not in credentials.config_path().read_text(encoding="utf-8")
    assert keyring.stored == {(credentials.SERVICE, "me"): "hunter2"}
    assert credentials.gbif_credentials() == credentials.Credentials(
        username="me", password="hunter2", source=credentials.KEYRING
    )


def test_a_machine_without_a_keyring_falls_back_to_the_credentials_file():
    assert credentials.store_gbif("me", "hunter2") == credentials.CONFIG_FILE
    assert credentials.gbif_credentials() == credentials.Credentials(
        username="me", password="hunter2", source=credentials.CONFIG_FILE
    )


@pytest.mark.skipif(platform.system() == "Windows", reason="no group or other mode bits")
def test_the_credentials_file_is_written_readable_only_by_its_owner():
    credentials.store_gbif("me", "hunter2")
    path = credentials.config_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not credentials.readable_by_other_users(path)


@pytest.mark.skipif(platform.system() == "Windows", reason="no group or other mode bits")
def test_a_world_readable_credentials_file_is_refused_rather_than_read():
    credentials.store_gbif("me", "hunter2")
    path = credentials.config_path()
    path.chmod(0o644)
    lookup = unusable()
    assert lookup.code == credentials.UNREADABLE
    assert "chmod 600" in lookup.detail


def test_a_credentials_file_that_will_not_parse_says_so():
    credentials.store_gbif("me", "hunter2")
    credentials.config_path().write_text("gbif: [unclosed\n", encoding="utf-8")
    credentials.config_path().chmod(0o600)
    assert unusable().code == credentials.UNREADABLE


def test_a_netrc_entry_for_the_gbif_api_host_is_used_when_nothing_else_holds_one(
    tmp_path, monkeypatch
):
    path = tmp_path / "netrc"
    path.write_text(
        f"machine {credentials.GBIF_HOST} login me password hunter2\n", encoding="utf-8"
    )
    path.chmod(0o600)
    monkeypatch.setattr(credentials, "_netrc_path", lambda: path)
    assert credentials.gbif_credentials() == credentials.Credentials(
        username="me", password="hunter2", source=credentials.NETRC
    )


@pytest.mark.skipif(platform.system() == "Windows", reason="no group or other mode bits")
def test_a_world_readable_netrc_is_refused_rather_than_read(tmp_path, monkeypatch):
    path = tmp_path / "netrc"
    path.write_text(
        f"machine {credentials.GBIF_HOST} login me password hunter2\n", encoding="utf-8"
    )
    path.chmod(0o644)
    monkeypatch.setattr(credentials, "_netrc_path", lambda: path)
    lookup = unusable()
    assert lookup.code == credentials.UNREADABLE
    assert "chmod 600" in lookup.detail


def test_a_netrc_without_an_entry_for_gbif_is_not_credentials(tmp_path, monkeypatch):
    path = tmp_path / "netrc"
    path.write_text("machine example.org login me password hunter2\n", encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(credentials, "_netrc_path", lambda: path)
    assert unusable().code == credentials.MISSING


def test_a_stored_username_whose_password_is_gone_reports_partial(keyring):
    credentials.store_gbif("me", "hunter2")
    keyring.stored.clear()
    lookup = unusable()
    assert lookup.code == credentials.PARTIAL
    assert "me" in lookup.detail


@pytest.mark.skipif(platform.system() == "Windows", reason="no group or other mode bits")
def test_storing_leaves_the_mode_of_a_config_directory_that_already_existed():
    directory = credentials.config_dir()
    directory.mkdir(parents=True)
    directory.chmod(0o755)
    credentials.store_gbif("me", "hunter2")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755


@pytest.mark.skipif(platform.system() == "Windows", reason="no group or other mode bits")
def test_storing_creates_a_config_directory_only_its_owner_can_enter():
    credentials.store_gbif("me", "hunter2")
    assert stat.S_IMODE(credentials.config_dir().stat().st_mode) == 0o700


def test_a_credentials_file_that_cannot_be_written_leaves_no_keyring_entry_behind(
    keyring, monkeypatch
):
    def refuse(settings):
        raise OSError("disk full")

    monkeypatch.setattr(credentials, "_write_settings", refuse)
    with pytest.raises(OSError):
        credentials.store_gbif("me", "hunter2")
    assert keyring.stored == {}


def test_clear_removes_the_keyring_entry_and_the_file(keyring):
    credentials.store_gbif("me", "hunter2")
    cleared = credentials.clear_gbif()
    assert set(cleared.places) == {credentials.KEYRING, credentials.CONFIG_FILE}
    assert cleared.left_behind is None
    assert keyring.stored == {}
    assert not credentials.config_path().exists()
    assert unusable().code == credentials.MISSING


def test_clear_says_nothing_was_stored_when_nothing_was(keyring):
    assert credentials.clear_gbif() == credentials.Cleared([])


def test_clear_says_when_an_unreadable_file_hides_the_keyring_entry_it_cannot_remove(keyring):
    credentials.store_gbif("me", "hunter2")
    credentials.config_path().write_text("gbif: [unclosed\n", encoding="utf-8")
    cleared = credentials.clear_gbif()
    assert cleared.places == [credentials.CONFIG_FILE]
    assert cleared.left_behind is not None
    assert "keyring" in cleared.left_behind
    assert keyring.stored == {(credentials.SERVICE, "me"): "hunter2"}


def test_the_summary_names_the_account_and_its_source_but_never_the_password(keyring):
    credentials.store_gbif("me", "hunter2")
    summary = credentials.gbif_summary(credentials.gbif_credentials())
    assert "me" in summary
    assert credentials.KEYRING in summary
    assert "hunter2" not in summary


def test_the_config_directory_follows_the_environment_override(monkeypatch, tmp_path):
    monkeypatch.setenv(credentials.CONFIG_DIR_ENV, str(tmp_path / "elsewhere"))
    assert credentials.config_path() == tmp_path / "elsewhere" / credentials.CONFIG_FILENAME
