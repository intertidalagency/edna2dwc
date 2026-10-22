from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
import json
import sys

import keyring
from keyring.backends import fail
import pytest

from edna2dwc.cli import app
from edna2dwc.common.result import CommandResult
from edna2dwc.taxonomy import register_http
from edna2dwc.validation import credentials


@pytest.fixture(autouse=True)
def isolated_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(credentials.USER_ENV, raising=False)
    monkeypatch.delenv(credentials.PASS_ENV, raising=False)
    monkeypatch.setenv(credentials.CONFIG_DIR_ENV, str(tmp_path / "config"))
    monkeypatch.setattr(credentials, "_netrc_path", lambda: tmp_path / "absent-netrc")


@pytest.fixture(autouse=True)
def no_usable_keyring() -> Iterator[None]:
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def instant_register_retries(monkeypatch) -> None:
    monkeypatch.setattr(register_http, "sleep", lambda _seconds: None)


@pytest.fixture
def run_cli(capsys) -> Callable[[Sequence[str]], CommandResult]:
    def run(argv: Sequence[str]) -> CommandResult:
        result = app(
            argv,
            result_action="return_value",
            exit_on_error=False,
            print_error=False,
        )
        if "--json" in argv:
            printed = capsys.readouterr().out
            if printed:
                json.loads(printed)
            sys.stdout.write(printed)
        return result

    return run
