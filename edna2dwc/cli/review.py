from __future__ import annotations

from pathlib import Path
import shutil
from typing import Annotated

from cyclopts import App, Parameter
from cyclopts.types import ExistingDirectory, ExistingFile

from edna2dwc.cli.app import app
from edna2dwc.cli.common import CommandFailed, JsonFlag, UsageError
from edna2dwc.cli.groups import stage
from edna2dwc.common import findings
from edna2dwc.common.result import CommandResult
from edna2dwc.conversion import artifacts
from edna2dwc.review import audit, report

audit_app = App(
    **stage("audit"),
    help="Check that every value in the archive came from somewhere.",
)

app.command(audit_app)


@audit_app.command(
    name="prompt", usage="Usage: edna2dwc audit prompt ARCHIVE_DIR --source PATH [OPTIONS]"
)
def audit_prompt(
    archive_dir: Path,
    /,
    *,
    sources: Annotated[tuple[Path, ...], Parameter(name="--source", negative="")],
) -> CommandResult:
    """Print the fabrication-audit prompt for an agent with no other context to run against an archive.

    Args:
        archive_dir: The finished archive directory to audit.
        sources: A raw input file the archive was converted from. Repeatable.
    """
    return CommandResult(
        command="audit prompt",
        text=audit.build_audit_prompt(
            source_paths=[str(s) for s in sources], archive_dir=str(archive_dir)
        ),
    )


@audit_app.command(name="record")
def audit_record(
    archive_dir: ExistingDirectory,
    /,
    *,
    from_file: Annotated[ExistingFile, Parameter(name="--from-file")],
) -> CommandResult:
    """Record an independent fabrication audit's result against an archive, in audit_record.json beside answers.yaml.

    Run in the conversion directory. When the archive is built, it rewrites CONVERSION_REPORT.md there to list the findings for a person to read, and puts the record in reproduce/. It changes no status or exit code, and needs no rebuild.

    Args:
        archive_dir: The audited archive directory.
        from_file: The auditor's result, one JSON object: {"findings": ["<one sentence per finding>"]}, with an empty list when nothing turned up.
    """
    try:
        findings = audit.load_audit_result(from_file)
    except ValueError as e:
        raise CommandFailed(str(e)) from e
    audit.record_audit(artifacts.AUDIT_RECORD, findings, archive_dir=archive_dir)
    text = [f"Recorded {len(findings)} audit finding(s) for {archive_dir}."]
    pages = report.record_audit(archive_dir, findings)
    if pages is None:
        next_step = "`edna2dwc build`, so CONVERSION_REPORT.md lists them"
    else:
        bundled = archive_dir / artifacts.BUNDLE_DIR / artifacts.AUDIT_RECORD
        if bundled.parent.is_dir():
            shutil.copyfile(artifacts.AUDIT_RECORD, bundled)
        text.append(f"{pages[0]} lists them, and {bundled.parent} holds the record.")
        next_step = f"`edna2dwc evaluate {archive_dir}`"
    return CommandResult(command="audit record", text=" ".join(text), next_step=next_step)


@app.command(**stage("findings"))
def findings_cmd(*codes: str, as_json: JsonFlag = False) -> CommandResult:
    """Explain finding codes: every code, or only the ones given.

    Args:
        codes: Codes to explain, such as TAXON_FUZZY_REJECTED. Without any, lists every code.
    """
    unknown = [code for code in codes if code not in findings.CODES]
    if unknown:
        raise UsageError(
            f"{', '.join(unknown)}: not a finding code. `edna2dwc findings` lists every code"
        )
    entries = [
        {
            "code": code,
            "severity": findings.severity_label(code),
            "meaning": findings.meaning(code),
        }
        for code in codes or sorted(findings.CODES)
    ]
    text = (
        "\n".join(f"{e['code']} ({e['severity']}): {e['meaning']}" for e in entries)
        if codes
        else findings.reference_table()
    )
    return CommandResult(command="findings", text=text, json_body=entries, as_json=as_json)
