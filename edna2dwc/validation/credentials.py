from __future__ import annotations

from dataclasses import dataclass
import netrc
import os
from pathlib import Path
import platform
from typing import cast

import keyring
from keyring.backends import fail
import platformdirs
import yaml

SERVICE = "edna2dwc"
GBIF_HOST = "api.gbif.org"
USER_ENV = "EDNA2DWC_GBIF_USER"
PASS_ENV = "EDNA2DWC_GBIF_PASS"
CONFIG_DIR_ENV = "EDNA2DWC_CONFIG_DIR"
CONFIG_FILENAME = "credentials.yaml"

ENVIRONMENT = "the environment"
KEYRING = "the OS keyring"
KEYRING_UNREAD = "the OS keyring, read only when GBIF validation runs"
KEYRING_OR_FILE_UNREAD = (
    "the OS keyring if it holds one, else the credentials file; the keyring is read only when "
    "GBIF validation runs"
)
CONFIG_FILE = "the credentials file"
NETRC = "~/.netrc"

MISSING = "GBIF_CREDENTIALS_MISSING"
PARTIAL = "GBIF_CREDENTIALS_PARTIAL"
UNREADABLE = "GBIF_CREDENTIALS_UNREADABLE"
REJECTED = "GBIF_CREDENTIALS_REJECTED"

SET_HINT = "run `edna2dwc credentials set --gbif` in your own terminal"
_OTHER_USERS_MODE = 0o077


@dataclass(frozen=True)
class Account:
    username: str
    source: str


@dataclass(frozen=True)
class Credentials(Account):
    password: str


@dataclass(frozen=True)
class Unavailable:
    code: str
    detail: str


@dataclass(frozen=True)
class Cleared:
    places: list[str]
    left_behind: str | None = None


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override)
    return Path(platformdirs.user_config_dir(SERVICE))


def config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


def _netrc_path() -> Path:
    return Path.home() / ".netrc"


def _stored_password(username: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, username)
    except Exception:  # noqa: BLE001
        return None


def _store_password(username: str, password: str) -> bool:
    try:
        keyring.set_password(SERVICE, username, password)
    except Exception:  # noqa: BLE001
        return False
    return True


def _delete_stored_password(username: str) -> bool:
    try:
        keyring.delete_password(SERVICE, username)
    except Exception:  # noqa: BLE001
        return False
    return True


def _has_usable_keyring() -> bool:
    return not isinstance(keyring.get_keyring(), fail.Keyring)


def readable_by_other_users(path: Path) -> bool:
    if platform.system() == "Windows":
        return False
    return bool(path.stat().st_mode & _OTHER_USERS_MODE)


def _settings() -> dict | Unavailable:
    path = config_path()
    if not path.exists():
        return {}
    if readable_by_other_users(path):
        return Unavailable(
            UNREADABLE,
            f"{path} is readable by other users; run `chmod 600 {path}` and try again",
        )
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return dict(loaded.get("gbif") or {})
    except (OSError, yaml.YAMLError, AttributeError, TypeError) as error:
        return Unavailable(UNREADABLE, f"{path} could not be read: {error}")


def _from_environment() -> Credentials | Unavailable | None:
    username = (os.environ.get(USER_ENV) or "").strip()
    password = os.environ.get(PASS_ENV) or ""
    if username and password:
        return Credentials(username=username, password=password, source=ENVIRONMENT)
    if username or password:
        given, absent = (USER_ENV, PASS_ENV) if username else (PASS_ENV, USER_ENV)
        return Unavailable(
            PARTIAL,
            f"{given} is set but {absent} is not, so neither was used; set both, or {SET_HINT}",
        )
    return None


def _from_netrc() -> Credentials | Unavailable | None:
    path = _netrc_path()
    if not path.exists():
        return None
    if readable_by_other_users(path):
        return Unavailable(
            UNREADABLE,
            f"{path} is readable by other users; run `chmod 600 {path}` and try again",
        )
    try:
        entry = netrc.netrc(str(path)).authenticators(GBIF_HOST)
    except (netrc.NetrcParseError, OSError) as error:
        return Unavailable(UNREADABLE, f"{path} could not be read: {error}")
    if entry is None or not entry[0] or not entry[2]:
        return None
    return Credentials(username=entry[0], password=entry[2], source=NETRC)


def _lookup(*, read_keyring: bool) -> Account | Unavailable:
    from_environment = _from_environment()
    if from_environment is not None:
        return from_environment

    settings = _settings()
    if isinstance(settings, Unavailable):
        return settings

    username = (settings.get("username") or "").strip()
    if username:
        written = settings.get("password") or ""
        if not read_keyring:
            if not written:
                return Account(username=username, source=KEYRING_UNREAD)
            if _has_usable_keyring():
                return Account(username=username, source=KEYRING_OR_FILE_UNREAD)
        stored = _stored_password(username) if read_keyring else None
        if stored:
            return Credentials(username=username, password=stored, source=KEYRING)
        if written:
            return Credentials(username=username, password=written, source=CONFIG_FILE)

    from_netrc = _from_netrc()
    if from_netrc is not None:
        return from_netrc

    if username:
        return Unavailable(
            PARTIAL,
            f"{config_path()} names the account {username!r}, but neither the OS keyring "
            f"nor the file itself has a password for it; {SET_HINT}",
        )
    return Unavailable(
        MISSING,
        f"no GBIF account is configured, so GBIF validation is not measured; {SET_HINT}",
    )


def gbif_account() -> Account | Unavailable:
    return _lookup(read_keyring=False)


def gbif_credentials() -> Credentials | Unavailable:
    return cast(Credentials | Unavailable, _lookup(read_keyring=True))


def _write_settings(settings: dict) -> None:
    path = config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        yaml.safe_dump({"gbif": settings}, handle, sort_keys=False)
    os.chmod(path, 0o600)


def store_gbif(username: str, password: str) -> str:
    _write_settings({"username": username})
    if _store_password(username, password):
        return KEYRING
    _write_settings({"username": username, "password": password})
    return CONFIG_FILE


def clear_gbif() -> Cleared:
    settings = _settings()
    left_behind = None
    if isinstance(settings, Unavailable):
        left_behind = (
            f"{settings.detail}, so the account it names is unknown and any password the OS "
            "keyring stores for it under the service 'edna2dwc' was left in place"
        )
        settings = {}
    username = (settings.get("username") or "").strip()
    places = []
    if username and _delete_stored_password(username):
        places.append(KEYRING)
    path = config_path()
    if path.exists():
        path.unlink()
        places.append(CONFIG_FILE)
    return Cleared(places, left_behind)


def gbif_summary(lookup: Account | Unavailable) -> str:
    if isinstance(lookup, Account):
        return f"GBIF credentials: configured (user: {lookup.username}, from {lookup.source})"
    return f"GBIF credentials: not configured, {lookup.detail}"
