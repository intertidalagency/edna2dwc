from __future__ import annotations

import os
import sys
from typing import Annotated

from cyclopts import App, Group, Parameter

from edna2dwc.cli import run_log
from edna2dwc.cli.common import CommandFailed, UsageError
from edna2dwc.cli.groups import OPTIONS
from edna2dwc.cli.help import FlatFormatter
from edna2dwc.common import progress
from edna2dwc.common.result import CommandResult
from edna2dwc.common.table import ResourceLimitError
from edna2dwc.common.version import installed_version


def render(result: CommandResult | None) -> int:
    if result is None:
        return 0
    run_log.record_result(result)
    text = result.render()
    if text:
        print(text)
    return result.exit_code


ABOUT = """Convert eDNA and metabarcoding data into Darwin Core Archives for GBIF and OBIS.

Inspect your data files, read them into one table with a script of your own, resolve its taxonomy, build an archive from that table and your answers, and evaluate the result. A value missing from the inputs is left blank and reported. build reads answers.yaml, occurrence_long.tsv, resolved_taxonomy.tsv, confirmed/ and audit_record.json, and writes REVIEW.md.

For example:
  edna2dwc inspect data/
  edna2dwc init --dataset-id my-survey-2025
  python read_inputs.py
  edna2dwc record-step --config conversion.yaml --script read_inputs.py --raw data/counts.xlsx --command "python scripts/read_inputs.py"
  edna2dwc assemble --counts tables/counts.csv --features tables/taxonomy.csv
  edna2dwc resolve-taxonomy
  edna2dwc build
  edna2dwc evaluate archive/
"""

WHERE_NEXT = """Run 'edna2dwc <command> --help' for its options.
Docs: https://github.com/intertidalagency/edna2dwc/tree/main/docs"""


app = App(
    name="edna2dwc",
    usage="Usage: edna2dwc <command> [options]",
    help=ABOUT,
    help_epilogue=WHERE_NEXT,
    help_format="plaintext",
    help_formatter=FlatFormatter(),
    group_commands=OPTIONS,
    version=f"edna2dwc {installed_version()}",
    help_on_error=False,
    result_action=[render, "sys_exit"],
)


app.meta.group_parameters = Group("Options")


@app.meta.default
def launcher(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    quiet: Annotated[
        bool, Parameter(name="--quiet", negative="", help="Suppress progress output on stderr.")
    ] = False,
) -> CommandResult | None:
    """Run a command."""
    if quiet:
        progress.set_quiet(True)
    return app(tokens)


def main() -> None:
    argv = sys.argv[1:]
    with run_log.logging_invocation(argv):
        try:
            app.meta(argv)
        except UsageError as error:
            run_log.record_error(error)
            print(f"Error: {error}", file=sys.stderr)
            raise SystemExit(2) from None
        except (CommandFailed, ResourceLimitError) as error:
            run_log.record_error(error)
            print(f"Error: {error}", file=sys.stderr)
            raise SystemExit(1) from None
        except BrokenPipeError:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
            raise SystemExit(1) from None
