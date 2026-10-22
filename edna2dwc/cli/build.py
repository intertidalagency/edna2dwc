from __future__ import annotations

from pathlib import Path

from edna2dwc.build import packaging
from edna2dwc.cli.app import app
from edna2dwc.cli.common import (
    CommandFailed,
    Flag,
    JsonFlag,
    UsageError,
)
from edna2dwc.cli.groups import stage
from edna2dwc.common.result import CommandResult
from edna2dwc.conversion import artifacts

ARCHIVE_BUILT = "Archive built at"

ERROR_PREFIX = "Error: "

ACCEPTED_BY_AUTOMATIC = ("PROPOSAL_ACCEPTED", "UNCONFIRMED_ACCEPTED")


@app.command(**stage("build"))
def build_cmd(*, automatic: Flag = False, as_json: JsonFlag = False) -> CommandResult:
    """Build the archive from answers.yaml, conversion.yaml, occurrence_long.tsv, resolved_taxonomy.tsv, confirmed/, audit_record.json, assembly.json and the files answers.yaml names.

    Runs in the conversion directory and rebuilds everything each time. Writes each proposal to proposed/ and applies any sheet of the same name in confirmed/, row by row: a confirmed sheet holds the proposal's header and only the rows a person changed, so a header alone accepts the proposal. The control roster has no confirmed sheet: controls: in answers.yaml settles any sample. Never calls a taxonomic register: run resolve-taxonomy first. Writes REVIEW.md, which lists what is waiting on you. Exits 1 when the build ends in error, 2 when it refuses answers.yaml, the intermediate table or a confirmed sheet, and 0 otherwise.

    Args:
        automatic: Use every proposal nobody confirmed and every answer with confirmed: empty as written, logging each.
    """
    try:
        result = packaging.build(Path(), automatic=automatic)
    except packaging.UnwritableConversionDirectory as error:
        raise CommandFailed(str(error)) from error
    if result.refused:
        raise UsageError(result.detail)

    outputs = {"review_page": str(artifacts.REVIEW_PAGE)}
    text = []
    if result.archive_dir is not None:
        outputs["archive_dir"] = str(result.archive_dir)
        text.append(f"{ARCHIVE_BUILT} {result.archive_dir}.")
    if result.status == "error":
        text.append(f"{ERROR_PREFIX}{result.detail}")
    elif result.status != "ok":
        text.append(f"{result.status}: {result.detail}")
    if result.archive_dir is not None:
        text += [
            f"Accepted by --automatic: {f['message']}"
            for f in result.findings
            if f["code"] in ACCEPTED_BY_AUTOMATIC
        ]
    text.append(f"What is waiting on you, and how to close it: {artifacts.REVIEW_PAGE}")
    return CommandResult(
        command="build",
        status=result.status,
        findings=result.findings,
        outputs=outputs,
        next_step=result.next_step,
        stage=result.stage,
        text="\n".join(text),
        as_json=as_json,
        exit_code=result.exit_code,
    )
