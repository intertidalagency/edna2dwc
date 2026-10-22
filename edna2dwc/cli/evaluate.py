from __future__ import annotations

from typing import Annotated

from cyclopts import Parameter
from cyclopts.types import ExistingDirectory, ExistingFile

from edna2dwc.cli.app import app
from edna2dwc.cli.common import (
    Flag,
    IntermediateIn,
    JsonFlag,
    TermsTableIn,
    UsageError,
    validate_with_gbif,
)
from edna2dwc.cli.groups import stage
from edna2dwc.common.result import CommandResult
from edna2dwc.terms.term_table import load_term_table
from edna2dwc.validation import evaluate, validate


@app.command(**stage("validate"))
def validate_cmd(
    archive_dir: ExistingDirectory,
    /,
    *,
    strict: Flag = False,
    priority_terms: Flag = False,
    terms_table: TermsTableIn = None,
    intermediate_path: IntermediateIn = None,
    excluded_report_path: Annotated[
        ExistingFile | None, Parameter(name="--excluded-report")
    ] = None,
    gbif: Flag = False,
    obis: Flag = False,
    adjudications_path: Annotated[ExistingFile | None, Parameter(name="--adjudications")] = None,
    as_json: JsonFlag = False,
) -> CommandResult:
    """Check an archive's structure, term names, value formats, and the terms that must appear together.

    Args:
        archive_dir: The archive directory, not the zip.
        strict: Also fail on any column that isn't a Darwin Core term.
        priority_terms: Also check the priority eDNA terms rated required or strongly recommended.
        terms_table: A Darwin Core term table to use instead of the bundled one.
        intermediate_path: occurrence_long.tsv, to check every row is accounted for.
        excluded_report_path: excluded_rows_report.tsv, if rows were removed before build.
        gbif: Also submit dwca.zip to the GBIF validation API.
        obis: Also run the OBIS QC rules on the core table.
        adjudications_path: A YAML file whose adjudications: section accepts validator issues, such as answers.yaml.
    """
    try:
        return validate.step(
            archive_dir=archive_dir,
            term_table=load_term_table(terms_table),
            strict=strict,
            priority_terms=priority_terms,
            intermediate_path=intermediate_path,
            excluded_report_path=excluded_report_path,
            gbif=validate_with_gbif if gbif else None,
            obis=obis,
            adjudications=validate.load_adjudications(adjudications_path),
            as_json=as_json,
        )
    except validate.AdjudicationsError as e:
        raise UsageError(str(e)) from e


@app.command(**stage("evaluate"))
def evaluate_cmd(
    archive_dir: ExistingDirectory,
    /,
    *,
    gbif: Flag = False,
    terms_table: TermsTableIn = None,
    mapping_path: Annotated[ExistingFile | None, Parameter(name="--mapping")] = None,
    term_states_path: Annotated[ExistingFile | None, Parameter(name="--term-states")] = None,
    intermediate_path: IntermediateIn = None,
    excluded_report_path: Annotated[
        ExistingFile | None, Parameter(name="--excluded-report")
    ] = None,
    adjudications_path: Annotated[ExistingFile | None, Parameter(name="--adjudications")] = None,
    as_json: JsonFlag = False,
) -> CommandResult:
    """Check a finished archive and write EVALUATION.md saying what it lacks.

    Runs the OBIS checks and the term, mapping and row checks, and with --gbif the GBIF validator. A check whose input is missing is reported as not measured, never as passed. Exits non-zero unless every check passes, apart from the advisory check of strongly recommended terms. Without --gbif, the GBIF check reads not measured and doesn't decide the exit code.

    Args:
        archive_dir: The archive directory, not the zip.
        gbif: Also submit the archive to the GBIF validation API, using the account from credentials set --gbif. Reading a password from the OS keyring can bring up a system prompt, so ask the user first.
        terms_table: A Darwin Core term table to use instead of the bundled one.
        mapping_path: term_mapping.tsv. Defaults to the one in the conversion directory whose answers.yaml out_dir is the archive, else in the current directory.
        term_states_path: term_states.tsv, likewise.
        intermediate_path: occurrence_long.tsv, likewise.
        excluded_report_path: excluded_rows_report.tsv, likewise.
        adjudications_path: A YAML file whose adjudications: section accepts validator issues, such as answers.yaml. Defaults to the bundled answers.yaml.
    """
    try:
        return evaluate.step(
            archive_dir=archive_dir,
            term_table=load_term_table(terms_table),
            mapping_path=mapping_path,
            term_states_path=term_states_path,
            intermediate_path=intermediate_path,
            excluded_report_path=excluded_report_path,
            adjudications_path=adjudications_path,
            gbif=validate_with_gbif if gbif else None,
            as_json=as_json,
        )
    except validate.AdjudicationsError as e:
        raise UsageError(str(e)) from e
