from __future__ import annotations

from pathlib import Path

from cyclopts import App

from edna2dwc.cli.app import app
from edna2dwc.cli.common import CommandFailed, Flag, OutputPath
from edna2dwc.cli.groups import stage
from edna2dwc.common.result import CommandResult
from edna2dwc.terms import sync

terms = App(
    **stage("terms"),
    help="Maintain the vendored term table by hand. Never run in CI.",
)
app.command(terms)


@terms.command(name="sync")
def terms_sync_cmd(
    *, offline: Flag = False, output: OutputPath = Path("dwc_terms.json")
) -> CommandResult:
    """Fetch dwc_terms.json from the live Darwin Core term registries.

    Args:
        offline: Use the registry responses cached by an earlier live run.
        output: Where to write the term table.
    """
    try:
        return sync.step(offline=offline, output=output)
    except FileNotFoundError as e:
        raise CommandFailed(str(e)) from e
    except ValueError as e:
        raise CommandFailed(str(e)) from e
