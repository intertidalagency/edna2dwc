from __future__ import annotations

from datetime import UTC, datetime
import getpass
import importlib
from pathlib import Path
import platform
import shutil
import sys
from typing import Annotated

from cyclopts import App, Parameter
from cyclopts.types import ExistingDirectory
import httpx

from edna2dwc.build import packaging
from edna2dwc.cli.app import app
from edna2dwc.cli.common import (
    PACKAGE_DIR,
    CommandFailed,
    JsonFlag,
    UsageError,
    require_iso_datetime,
)
from edna2dwc.cli.groups import stage
from edna2dwc.common import table
from edna2dwc.common.result import ERROR, OK, CommandResult
from edna2dwc.common.version import installed_version
from edna2dwc.conversion import answers, artifacts
from edna2dwc.conversion.answers import DatasetIdError, validate_dataset_id
from edna2dwc.dwca.manifest import Manifest, init_scan
from edna2dwc.reproduce.environment import READER_PACKAGES
from edna2dwc.validation import credentials
from edna2dwc.validation.gbif_validator import credentials_accepted

SKILL_PATH_MODULES = (
    "edna2dwc.common.result",
    "edna2dwc.common.findings",
    "edna2dwc.common.progress",
    "edna2dwc.inputs.inspect",
    "edna2dwc.inputs.detect_redundant",
    "edna2dwc.conversion.answers",
    "edna2dwc.dwca.manifest",
    "edna2dwc.common.tsv",
    "edna2dwc.conversion.intermediate",
    "edna2dwc.reproduce.steps_log",
    "edna2dwc.build.packaging",
    "edna2dwc.terms.map_terms",
    "edna2dwc.review.audit",
    "edna2dwc.review.report",
    "edna2dwc.reproduce.replay",
)


def _importable(name: str) -> bool:
    try:
        importlib.import_module(name)
    except Exception:  # noqa: BLE001
        return False
    return True


def _credential_state(lookup: credentials.Account | credentials.Unavailable) -> dict:
    if isinstance(lookup, credentials.Account):
        return {"configured": True, "username": lookup.username, "source": lookup.source}
    return {"configured": False, "code": lookup.code, "detail": lookup.detail}


@app.command(**stage("doctor"))
def doctor(*, as_json: JsonFlag = False) -> CommandResult:
    """Check that this install is complete, and say where it is.

    Lists the packages a reader script may import and the python that has them. A replay runs each reader script with exactly these packages, at the versions the conversion recorded, so a script that imports anything else can't be replayed."""
    gbif_account = credentials.gbif_account()
    packages = {name: _importable(name) for name in READER_PACKAGES}
    modules = {name: _importable(name) for name in SKILL_PATH_MODULES}
    broken = [name for name, ok in modules.items() if not ok]
    name_width = max(len(name) for name in packages)
    text = [
        f"edna2dwc {installed_version()} (python {platform.python_version()})",
        f"installed at {PACKAGE_DIR}",
        f"python for reader scripts: {sys.executable}",
        "",
        "packages a reader script may import",
        *(f"  {name:<{name_width}}  {'ok' if ok else 'BROKEN'}" for name, ok in packages.items()),
        "",
        f"internal modules  {len(modules) - len(broken)} of {len(modules)} import",
        *(f"  {name}  BROKEN" for name in broken),
        "",
        (
            f"memory limit  {table.memory_limit()}, {table.memory_limit_source()}. Set "
            f"{table.MEMORY_LIMIT_ENV} to change it"
        ),
        (
            f"spill space   {table.in_gib(table.spill_free_bytes())} free in "
            f"{table.spill_dir()}, where DuckDB writes what doesn't fit in the memory limit. Set "
            "TMPDIR to move it"
        ),
        "",
        credentials.gbif_summary(gbif_account),
    ]
    healthy = all(packages.values()) and not broken
    if not healthy:
        text += ["", "Install is incomplete. Try: pip install --force-reinstall edna2dwc"]

    return CommandResult(
        command="doctor",
        status=OK if healthy else ERROR,
        json_body={
            "command": "doctor",
            "status": OK if healthy else ERROR,
            "edna2dwc_version": installed_version(),
            "python": platform.python_version(),
            "location": str(PACKAGE_DIR),
            "interpreter": sys.executable,
            "packages": packages,
            "modules": modules,
            "memory_limit": table.memory_limit(),
            "memory_limit_source": table.memory_limit_source(),
            "spill_dir": str(table.spill_dir()),
            "spill_free_bytes": table.spill_free_bytes(),
            "gbif_credentials": _credential_state(gbif_account),
        },
        text="\n".join(text),
        next_step="`edna2dwc inspect <the input files>`, run in the conversion directory"
        if healthy
        else None,
        as_json=as_json,
        exit_code=0 if healthy else 1,
    )


credentials_app = App(
    **stage("credentials"),
    help="Store the GBIF account 'evaluate --gbif' and 'validate --gbif' sign in with.",
)
app.command(credentials_app)


GbifFlag = Annotated[
    bool,
    Parameter(
        name="--gbif",
        negative="",
        help="Act on the GBIF account. Required.",
    ),
]


_NO_TERMINAL = (
    "A password can only be typed at a terminal, and this process has none. Run "
    "`edna2dwc credentials set --gbif` in your own terminal instead. In an agent session, "
    "prefix it with `!` so it runs in your shell, and never paste the password into the "
    "conversation."
)


@credentials_app.command(name="set")
def credentials_set(
    *,
    gbif: GbifFlag = False,
    username: str | None = None,
    no_verify: Annotated[
        bool,
        Parameter(
            name="--no-verify",
            negative="",
            help="Store the password without asking GBIF whether it works.",
        ),
    ] = False,
    as_json: JsonFlag = False,
) -> CommandResult:
    """Store a GBIF account, prompting for the password.

    The password is read at a prompt that does not echo it. There is no flag for it, so it never reaches the command line, shell history or an agent's transcript. It is stored in the OS keyring, or in a credentials file only you can read.

    Args:
        username: GBIF account name. Prompted for when omitted.
    """
    _require_gbif(gbif)
    if not sys.stdin.isatty():
        raise UsageError(_NO_TERMINAL)
    username = (username or input("GBIF username: ")).strip()
    password = getpass.getpass("GBIF password (not echoed): ")
    if not username or not password:
        raise UsageError("A GBIF username and password are both needed.")

    checked = False
    if not no_verify:
        candidate = credentials.Credentials(
            username=username, password=password, source="this prompt"
        )
        try:
            if not credentials_accepted(candidate):
                raise CommandFailed(
                    f"GBIF rejected the account {username!r} (HTTP 401), so nothing was "
                    "stored. Check it at https://www.gbif.org/user/profile."
                )
        except httpx.HTTPError as error:
            raise CommandFailed(
                f"GBIF could not be reached to check the account: {error}. Pass --no-verify "
                "to store it unchecked."
            ) from error
        checked = True

    source = credentials.store_gbif(username, password)
    return CommandResult(
        command="credentials set",
        json_body={
            "command": "credentials set",
            "username": username,
            "stored_in": source,
            "verified": checked,
            "config_file": str(credentials.config_path()),
        },
        text="\n".join(
            [
                f"Stored the GBIF account {username!r} in {source}.",
                f"Its username is recorded in {credentials.config_path()}.",
                "Checked against GBIF." if checked else "Not checked against GBIF.",
            ]
        ),
        as_json=as_json,
    )


@credentials_app.command(name="show")
def credentials_show(*, as_json: JsonFlag = False) -> CommandResult:
    """Show which GBIF account is configured and where it came from.

    Never prints or reads the password, and never contacts GBIF.
    """
    lookup = credentials.gbif_account()
    configured = isinstance(lookup, credentials.Account)
    text = [
        credentials.gbif_summary(lookup),
        "",
        "looked in, in this order",
        f"  environment       {credentials.USER_ENV} and {credentials.PASS_ENV}",
        f"  OS keyring        service {credentials.SERVICE!r}",
        f"  credentials file  {credentials.config_path()}",
        f"  netrc             ~/.netrc, machine {credentials.GBIF_HOST}",
    ]
    return CommandResult(
        command="credentials show",
        json_body={
            "command": "credentials show",
            "gbif": {
                "configured": configured,
                "username": lookup.username if configured else None,
                "source": lookup.source if configured else None,
                "code": None if configured else lookup.code,
                "detail": None if configured else lookup.detail,
            },
            "config_file": str(credentials.config_path()),
        },
        text="\n".join(text),
        as_json=as_json,
    )


@credentials_app.command(name="clear")
def credentials_clear(*, gbif: GbifFlag = False, as_json: JsonFlag = False) -> CommandResult:
    """Remove the stored GBIF account from this machine.

    An account set in the environment or ~/.netrc is not removed, and is reported if still there.
    """
    _require_gbif(gbif)
    cleared = credentials.clear_gbif()
    text = [f"Removed the stored GBIF account from {place}." for place in cleared.places] or [
        "Nothing was stored, so nothing was removed."
    ]
    if cleared.left_behind:
        text.append(f"{cleared.left_behind[0].upper()}{cleared.left_behind[1:]}.")
    remaining = credentials.gbif_credentials()
    if isinstance(remaining, credentials.Credentials):
        text.append(
            f"An account is still configured in {remaining.source}, which this command does "
            "not write and will not remove."
        )
    return CommandResult(
        command="credentials clear",
        json_body={
            "command": "credentials clear",
            "cleared": cleared.places,
            "left_behind": cleared.left_behind,
            "still_configured_in": remaining.source
            if isinstance(remaining, credentials.Credentials)
            else None,
        },
        text="\n".join(text),
        as_json=as_json,
    )


def _require_gbif(gbif: bool) -> None:
    if not gbif:
        raise UsageError("Pass --gbif: the GBIF account is the only credential this tool uses.")


JUSTFILE = Path("justfile")


@app.command(**stage("init"))
def init_cmd(
    *,
    dataset_id: str,
    out_dir: Path = Path("archive"),
    created: str | None = None,
    scan_dir: Annotated[ExistingDirectory | None, Parameter(name="--scan")] = None,
) -> CommandResult:
    """Start a conversion: write answers.yaml, conversion.yaml and the justfile in this directory.

    answers.yaml is a commented skeleton of everything a person decides about the dataset. edna2dwc never writes it again.

    Args:
        dataset_id: Stable identifier for this dataset, such as my-survey-2026. Must be non-blank and contain no colon. Never make up a DOI or URL: with none in the sources, use a short label from the study or file name.
        out_dir: Where the finished archive will be written: a directory of its own inside this one, which build empties every time.
        created: ISO 8601 datetime the conversion started. Defaults to now, in UTC.
        scan_dir: Directory to search for an eml.xml whose title, abstract, creators, contacts, geographic description, bounding box and publication date fill the metadata. With several, the first in sorted order is used.
    """
    if artifacts.ANSWERS.exists():
        raise UsageError(f"{artifacts.ANSWERS} already exists")
    try:
        validate_dataset_id(dataset_id)
    except DatasetIdError as error:
        raise UsageError(str(error)) from error
    if created is None:
        created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        require_iso_datetime(created, "--created")
    scan = init_scan(scan_dir) if scan_dir else None
    artifacts.ANSWERS.write_text(
        answers.skeleton(
            dataset_id=dataset_id,
            created=created,
            out_dir=out_dir,
            harvested=scan.manifest if scan else Manifest(),
        ),
        encoding="utf-8",
    )
    written = [artifacts.ANSWERS]
    for path, write in (
        (artifacts.CONFIG, lambda: artifacts.write_recipe(artifacts.CONFIG, {"steps": []})),
        (JUSTFILE, lambda: shutil.copyfile(packaging.JUSTFILE_TEMPLATE, JUSTFILE)),
    ):
        if not path.exists():
            write()
            written.append(path)
    text = [f"Wrote {', '.join(str(path) for path in written)}."]
    if scan and scan.eml_paths:
        text.append(f"Filled the metadata found in {scan.eml_paths[0]}.")
    if scan and len(scan.eml_paths) > 1:
        text.append(
            f"{len(scan.eml_paths)} eml.xml files were found under {scan_dir}: "
            f"{', '.join(str(path) for path in scan.eml_paths)}. Confirm the first describes "
            "this dataset, or correct its fields in answers.yaml."
        )
    return CommandResult(
        command="init",
        outputs={"written": [str(path) for path in written]},
        text=" ".join(text),
        next_step=(
            f"answer what {artifacts.ANSWERS} asks, from the documents first and then the "
            "researcher. Then Stage 3, Read: write the reader script"
        ),
    )
