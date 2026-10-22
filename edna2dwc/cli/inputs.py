from __future__ import annotations

import json
from pathlib import Path
import shlex
from typing import Annotated

from cyclopts import Parameter
from cyclopts.types import ExistingFile, ExistingPath

from edna2dwc.cli.app import app
from edna2dwc.cli.common import (
    CommandFailed,
    Flag,
    JsonFlag,
    TermsTableIn,
    UsageError,
)
from edna2dwc.cli.groups import stage
from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.result import CommandResult, render_findings
from edna2dwc.conversion import artifacts, intermediate
from edna2dwc.inputs import assemble, detect_redundant, document_text, inspect, inspection_page
from edna2dwc.reproduce import bundle, steps_log
from edna2dwc.terms.term_table import load_term_table


@app.command(**stage("inspect"))
def inspect_cmd(
    *paths: Annotated[ExistingPath, Parameter(required=True)],
    output_dir: Annotated[Path, Parameter(name=["-o", "--output"])] = Path(),
    terms_table: TermsTableIn = None,
    as_json: JsonFlag = False,
) -> CommandResult:
    """Look at your data files and write INSPECTION.md listing the terms an archive could fill.

    Names each file's format, the Darwin Core terms its columns supply, and the decisions the conversion will ask for. Reads nothing into the conversion.

    Args:
        paths: Files or directories to inspect. A directory means every non-hidden file under it.
        output_dir: Where to write INSPECTION.md and its HTML twin.
        terms_table: A Darwin Core term table to use instead of the bundled one.
    """
    reports = [inspect.inspect_path(path) for path in _files_under(paths)]
    term_table = load_term_table(terms_table)
    assessment = inspection_page.assess(reports, term_table)
    written = inspection_page.write(
        assessment, inputs=[str(p) for p in paths], directory=output_dir
    )
    text = []
    for report in reports:
        text.append(f"{report.path}, format: {report.format}")
        text.append(json.dumps(report.summary, indent=2))
        text.extend(f"  note: {note}" for note in report.notes)
    text.append("")
    text.append(f"Feature table: {', '.join(assessment.feature_tables) or 'none recognized'}")
    text.append(f"Terms supplied by a column: {len(assessment.found)}")
    text.append(
        "Terms nothing supplies: " + (", ".join(t.term for t in assessment.missing) or "none")
    )
    text.append(f"Wrote {written[0]} and {written[1]}.")
    return CommandResult(
        command="inspect",
        json_body=[r.to_dict() for r in reports],
        outputs={"page": str(written[0])},
        text="\n".join(text),
        next_step="`edna2dwc init --dataset-id <an ID the researcher will keep> --scan <the input directory>`",
        as_json=as_json,
    )


@app.command(**stage("text"))
def text_cmd(
    *paths: Annotated[ExistingFile, Parameter(required=True)],
    as_json: JsonFlag = False,
) -> CommandResult:
    """Print the text of a PDF, DOCX, XLSX or text file, so nobody writes a parser to read one.

    Prints each sheet of a workbook as tab-separated rows under its name. Reads nothing into the conversion.

    Args:
        paths: The documents or workbooks to read.
    """
    texts: dict[str, str | None] = {}
    sections = []
    for path in paths:
        try:
            texts[str(path)] = document_text.document_text(path)
            sections.append(f"==> {path} <==\n{texts[str(path)]}")
        except document_text.UnreadableDocument as error:
            texts[str(path)] = None
            sections.append(f"==> {path} <==\nunreadable: {error}")
    return CommandResult(
        command="text", json_body=texts, text="\n".join(sections), as_json=as_json
    )


def _files_under(paths: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(
                p
                for p in sorted(path.rglob("*"))
                if p.is_file()
                and not any(part.startswith(".") for part in p.relative_to(path).parts)
            )
        else:
            files.append(path)
    return files


@app.command(**stage("detect-redundant"))
def detect_redundant_cmd(
    *paths: Annotated[ExistingFile, Parameter(required=True)],
    tolerance: float = detect_redundant.DEFAULT_TOLERANCE,
    as_json: JsonFlag = False,
) -> CommandResult:
    """Fingerprint each input and report which pairs look like duplicates.

    Args:
        paths: The input files to compare.
        tolerance: Relative tolerance when comparing totals.
    """
    try:
        report = detect_redundant.detect_redundant_paths(list(paths), tolerance=tolerance)
    except ValueError as e:
        raise CommandFailed(str(e)) from e

    text = [f"FAILED: {path}: {failure}" for path, failure in report.failures.items()]
    text += [f"{a} vs {b}: {v}" for (a, b), v in report.verdicts.items()]
    return CommandResult(
        command="detect-redundant",
        json_body=report.to_dict(),
        text="\n".join(text),
        as_json=as_json,
    )


Paths = Annotated[tuple[ExistingFile, ...], Parameter(negative="")]


def _refuse_inputs_outside_tables(paths: tuple[Path, ...]) -> None:
    tables = artifacts.TABLES_DIR.resolve()
    outside = [path.as_posix() for path in paths if not path.resolve().is_relative_to(tables)]
    if outside:
        raise UsageError(
            f"assemble reads only the tables a reader script wrote to {artifacts.TABLES_DIR}/, "
            f"and these are outside it: {', '.join(outside)}. Write a reader script that reads "
            f"each one into {artifacts.TABLES_DIR}/, even if it only copies it, and record it "
            "with edna2dwc record-step --config conversion.yaml --script <script> --command "
            '"python scripts/<script> <file>" --raw <file>, so a replay can write the table '
            "again. Then run assemble on the tables it wrote"
        )


@app.command(**stage("assemble"), usage="Usage: edna2dwc assemble --counts PATH [OPTIONS]")
def assemble_cmd(
    *,
    counts: Annotated[tuple[ExistingFile, ...], Parameter(required=True, negative="")],
    features: Paths = (),
    samples: Paths = (),
    sequences: Paths = (),
    keep_zeros: Flag = False,
    as_json: JsonFlag = False,
) -> CommandResult:
    """Join the tables a reader script wrote into occurrence_long.tsv, and record the step.

    The reader script reads each input format into plain CSV or TSV tables, keyed by a featureID or sampleID column. assemble does the rest the same way every time: a zero count is dropped and reported, a wide count table becomes one row per nonzero cell, every table joins on its key, and a FASTA joins onto featureID as the sequence column. A join never drops a row: a key with no counterpart keeps its row with blank columns and is reported. A key repeated in a features or samples table, or a column two tables both give, stops it. It records itself in conversion.yaml after the reader scripts, reports each input's rows and count total to the conversion report, and checks the table it wrote. Run it in the conversion directory.

    It reads only files under tables/, where the reader scripts write, and refuses any other: a replay writes tables/ again by running the recorded reader scripts, so a file outside it would be missing. Read a source file that needs no reshaping into tables/ with a reader script too, recorded with record-step --raw.

    Args:
        counts: A count table under tables/: long, with sampleID, featureID and count columns, or wide, with featureID, an optional marker, and one column of counts per sample. Repeatable, as one table per marker.
        features: A table keyed by featureID, such as the taxonomy, with one row per feature. Repeatable: the tables are stacked, not joined, so give each feature in one of them.
        samples: A table keyed by sampleID, such as the sample metadata, with one row per sample. Repeatable: the tables are stacked, not joined, so give each sample in one of them.
        sequences: A FASTA whose record IDs are featureIDs. Repeatable.
        keep_zeros: Keep zero counts, from long and wide tables alike, for a targeted assay whose zeros build publishes as absences with derive_fields.emit_absences.
    """
    if not artifacts.CONFIG.exists():
        raise UsageError(
            f"{artifacts.CONFIG} is missing: run assemble in a conversion directory, after "
            "edna2dwc init, because it records itself there"
        )
    _refuse_inputs_outside_tables((*counts, *features, *samples, *sequences))
    sources = assemble.Sources(counts, features, samples, sequences, keep_zeros)
    try:
        assembled = assemble.assemble(sources, artifacts.INTERMEDIATE)
    except assemble.AssembleError as error:
        raise CommandFailed(str(error)) from error
    assemble.write_record(assembled, artifacts.ASSEMBLY, artifacts.INTERMEDIATE)
    command = ["edna2dwc", "assemble"]
    for flag, paths in (
        ("--counts", counts),
        ("--features", features),
        ("--samples", samples),
        ("--sequences", sequences),
    ):
        for path in paths:
            command += [flag, path.as_posix()]
    if keep_zeros:
        command.append("--keep-zeros")
    steps_log.record_tool_step(artifacts.CONFIG, shlex.join(command))
    checked = intermediate.validate_intermediate(artifacts.INTERMEDIATE)
    log = FindingsLog(assembled.findings.findings + checked.findings)
    wrote = (
        f"Wrote {assembled.rows} row(s) to {artifacts.INTERMEDIATE}, and recorded the step in "
        f"{artifacts.CONFIG}."
    )
    verdict = (
        f"{len(checked.findings)} problem(s) with {artifacts.INTERMEDIATE}."
        if checked.findings
        else f"OK: {artifacts.INTERMEDIATE} satisfies the intermediate table's schema."
    )
    return CommandResult.of(
        "assemble",
        log,
        text="\n".join(
            [
                wrote,
                render_findings(log),
                verdict,
            ]
        ),
        as_json=as_json,
        exits_on_error=True,
        next_step=(
            "fix the reader script, record it again with `edna2dwc record-step`, and run "
            "`edna2dwc assemble` again"
            if checked.has_errors()
            else "`edna2dwc resolve-taxonomy`"
        ),
    )


@app.command(**stage("validate-intermediate"))
def validate_intermediate(path: ExistingFile, /, *, as_json: JsonFlag = False) -> CommandResult:
    """Check that an occurrence_long.tsv file satisfies the intermediate table's schema.

    The table is tab-separated UTF-8, one row per sample and feature, with no tab or line break inside a value. It needs sampleID, featureID and count (a number, 0 or more), and a column naming the taxon: taxonomy, rank columns kingdom to genus, species or scientificName, in any case. It can't have scientificNameID, taxonRank, scientificNameAuthorship, taxonomicStatus or taxonConceptID, which resolve-taxonomy writes. A taxonomy value is one lineage, its ranks separated by ';' or '|' with optional k__-style prefixes, or labelled as 'Kingdom: Bacteria | Phylum: ...' with every segment labelled. A marker column names each row's marker, the key of its entry in answers.yaml's markers:, a sequence or DNA_sequence column holds the feature's DNA sequence, source_taxon_id holds a WoRMS AphiaID or LSID, and ncbi_taxid holds an NCBI taxonomy ID as a number or NCBI:txid<number>.

    Keep every other source column, named as the source names it. build maps a column whose name is a Darwin Core term or a known alias to that term. Any other column goes into dynamicProperties, and becomes measurement rows in the extendedmeasurementorfact extension when its name is a known measurement such as temperature or salinity, or nearly all its values are numbers. A measurement's unit comes from its header, as in temp_C or depth (m), or its values, as in 12.3 C, and units: in answers.yaml sets or corrects it. A value in a measurement column that isn't a number, such as a range, is published as written.

    Leave zero counts and no-assignment strings such as NA or unassigned as the source has them. assemble drops zero counts, and build reads those strings as empty.

    Exits 1 on any error.

    Args:
        path: The occurrence_long.tsv to check.
    """
    log = intermediate.validate_intermediate(path)
    if log.findings:
        text = f"{render_findings(log)}\n\n{len(log.findings)} finding(s)."
    else:
        text = f"OK: {path} satisfies the intermediate table's schema."
    return CommandResult.of(
        "validate-intermediate", log, text=text, as_json=as_json, exits_on_error=True
    )


@app.command(**stage("record-step"))
def record_step_cmd(
    *,
    config_path: Annotated[ExistingFile, Parameter(name="--config")],
    command_str: Annotated[str, Parameter(name="--command")],
    script: ExistingFile,
    raw_inputs: Annotated[tuple[ExistingFile, ...], Parameter(name="--raw", negative="")] = (),
    position: int | None = None,
) -> CommandResult:
    """Add a reader script to the steps: log in conversion.yaml, so replay runs it before build.

    Record every reader script that wrote the tables assemble joins, or replay will skip it. A new script goes after the other scripts and before assemble, which records itself. Recording a script already in the log again replaces its step in place, so record a changed script the same way; never edit steps: by hand. A replay runs each command under the recorded Python and package versions, with bare python on the path, from a copy of reproduce/ that holds only the recorded scripts, the raw inputs named in --raw and an empty tables/. So a step is refused when its command or its script names a path outside the conversion directory, an absolute path, or a file inside it that no --raw names.

    Args:
        config_path: conversion.yaml to append to.
        command_str: The exact command that ran, as a shell-pasteable string. It must run the vendored copy, scripts/<script name>, as in python scripts/read_inputs.py, because that is what a replay has.
        script: The reader script this step ran, copied to scripts/ under its own name.
        raw_inputs: A raw input file this step reads, copied into reproduce/ so a replay can find it. It must be inside the conversion directory, named in --command by a path relative to that directory. Repeatable.
        position: 1-based position to insert the step at. Defaults to after the other scripts, before assemble. A step must come before any step that reads its output.
    """
    try:
        steps_log.refuse_raw_inputs_outside(config_path.parent, raw_inputs)
        _refuse_a_step_a_replay_cannot_run(config_path, command_str, script, raw_inputs)
        step, replaced = steps_log.record_step(
            config_path,
            command=command_str,
            script=script,
            index=None if position is None else position - 1,
        )
    except ValueError as e:
        raise UsageError(str(e)) from e
    steps_log.record_raw_inputs(config_path, raw_inputs)
    text = [
        f"Replaced step {step.n} in {config_path}: {step.script} was recorded there before, "
        "so the new copy and hash took its place."
        if replaced
        else f"Recorded step {step.n}, {step.script}, in {config_path}."
    ]
    if step.command != command_str:
        text.append(
            "A secret-named variable this command assigned was left out of the recorded "
            "command: conversion.yaml ships with the archive, and a replay reads credentials "
            "from the machine it runs on. Set GBIF credentials with `edna2dwc credentials set "
            "--gbif` instead of assigning them on a command line."
        )
    return CommandResult(
        command="record-step",
        text="\n".join(text),
        next_step="`edna2dwc assemble` on the tables the script writes",
    )


def _refuse_a_step_a_replay_cannot_run(
    config_path: Path, command: str, script: Path, raw_inputs: tuple[Path, ...]
) -> None:
    project_dir = config_path.parent
    recorded = [step.script for step in steps_log.load_steps(config_path) if step.script]
    recipe = bundle.recipe_for_recording(
        project_dir,
        [*recorded, (steps_log.SCRIPTS_DIR / script.name).as_posix()],
        [*bundle.recorded_raw_inputs(config_path), *raw_inputs],
    )
    problems = bundle.check_step(recipe, command, script)
    if problems:
        raise UsageError(
            "A replay from reproduce/ could not run this step, so it was not recorded. "
            + " ".join(problems)
        )
