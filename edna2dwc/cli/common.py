from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from cyclopts import Parameter, validators
from cyclopts.types import ExistingPath
import httpx

import edna2dwc
from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.tsv import require_tab_separated
from edna2dwc.validation import credentials, gbif_validator

JsonFlag = Annotated[
    bool, Parameter(name="--json", negative="", help="Print JSON instead of text.")
]
Flag = Annotated[bool, Parameter(negative="")]


def _require_tab_separated(_type: object, path: Path | None) -> None:
    if path is not None:
        require_tab_separated(path)


TAB_SEPARATED_FILE = (validators.Path(exists=True, dir_okay=False), _require_tab_separated)
IntermediateIn = Annotated[
    Path | None, Parameter(name="--intermediate", validator=TAB_SEPARATED_FILE)
]
OutputPath = Annotated[Path, Parameter(name=["-o", "--output"])]
TermsTableIn = Annotated[ExistingPath | None, Parameter(name="--terms-table")]


class CommandLineError(Exception):
    pass


class UsageError(CommandLineError):
    pass


class CommandFailed(CommandLineError):
    pass


def require_iso_datetime(value: str, flag: str) -> None:
    try:
        datetime.fromisoformat(value)
    except ValueError as error:
        raise UsageError(f"{flag} must be an ISO 8601 datetime; got {value!r}") from error


PACKAGE_DIR = Path(edna2dwc.__file__).resolve().parent


def validate_with_gbif(
    zip_path: Path, adjudications: dict[str, str]
) -> tuple[FindingsLog, list[gbif_validator.GbifIssue]]:
    with httpx.Client(timeout=30) as client:
        return gbif_validator.run_gbif_validation(
            zip_path,
            credentials=credentials.gbif_credentials(),
            client=client,
            adjudications=adjudications,
        )
