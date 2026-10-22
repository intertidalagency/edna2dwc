from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import tempfile

import edna2dwc
from edna2dwc.build import (
    archive_dir,
    classify_samples,
    derive_fields,
    exclude_taxa,
    filter_controls,
    join_taxonomy,
    questions,
    sheets,
    synthesize_ids,
)
from edna2dwc.build.questions import QUANTITY_TYPE, MissingAnswer
from edna2dwc.build.result import BuildResult
from edna2dwc.build.sheets import (
    CONTROL_ROSTER,
    DERIVED_VALUES,
    TAXA,
    TERM_MAPPING,
    SheetReview,
)
from edna2dwc.build.synthesize_ids import CONSUMED_COLUMNS
from edna2dwc.common import tsv
from edna2dwc.common.findings import ERROR, JUDGED_BY_A_PERSON, FindingsLog
from edna2dwc.common.table import ROW, ResourceLimitError, Table, connect, write_tsv
from edna2dwc.common.tsv import read_tab_separated_header
from edna2dwc.conversion import answers as answers_file
from edna2dwc.conversion import artifacts, stages
from edna2dwc.conversion.answers import Answers, target_kingdoms
from edna2dwc.conversion.intermediate import (
    REQUIRED_COLUMNS,
    IntermediateInvalid,
    IntermediateMissing,
    markers,
    require_intermediate,
    require_valid,
)
from edna2dwc.conversion.provenance import Answer
from edna2dwc.dwca import emof, writer
from edna2dwc.dwca.eml import EmlRenderError, missing_profile_elements
from edna2dwc.inputs import assemble
from edna2dwc.reproduce import bundle, environment
from edna2dwc.review import audit, report, review_page
from edna2dwc.taxonomy import derive_lineage, lock, resolve_taxonomy
from edna2dwc.terms import map_terms, term_states
from edna2dwc.terms.map_terms import JOINED_FIELDS
from edna2dwc.terms.term_table import load_term_table
from edna2dwc.validation import validate

JUSTFILE_TEMPLATE = Path(edna2dwc.__file__).parent / "templates" / "justfile"

TERM_TABLE = load_term_table()

ADJUDICATION_NEEDED = "ADJUDICATION_NEEDED"

WORKING_COLUMNS = ("marker", "resolution_path")
CARRIED_COLUMNS = (*CONSUMED_COLUMNS, *WORKING_COLUMNS)


class UnwritableConversionDirectory(OSError):
    pass


class _Halt(Exception):
    def __init__(self, status: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _take(findings: FindingsLog, log: FindingsLog, step: str) -> None:
    findings.findings.extend(log.findings)
    if errors := _describe_errors(log):
        raise _Halt("error", f"{step}: {errors}")


def _recorded(result: BuildResult, findings: FindingsLog) -> list[dict]:
    halt = result.halt_finding
    return findings.to_list() + ([halt] if halt else [])


def _describe_errors(findings: FindingsLog) -> str:
    return "; ".join(
        f"{f.code}: {f.message}"
        for f in findings.findings
        if f.severity == ERROR and f.code != ADJUDICATION_NEEDED
    )


def _messages(findings: FindingsLog, codes: Collection[str]) -> list[str]:
    return [f.message for f in findings.findings if f.code in codes]


def _require_writable_directories(*directories: Path) -> None:
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=directory):
                pass
        except OSError as error:
            raise UnwritableConversionDirectory(
                f"{directory} rejected a new file: {error.strerror}. build writes there, so it "
                "cannot start. On macOS, your Documents, Desktop and Downloads folders are gated "
                "separately from the rest of your home directory, and access can be revoked "
                "with no dialog. Work outside them."
            ) from error


def _fresh(directory: Path) -> Path:
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    return directory


def _constant_by_marker(answers: Answers, table_markers: set[str], term: str) -> dict[str, str]:
    targets = answers.marker_targets(table_markers)
    values = {}
    for marker in table_markers:
        given = targets[marker].constants if marker in targets else {}
        if constant := given.get(term) or answers.constants.get(term):
            values[marker] = constant[0]
    return values


def _needs_decision(
    missing: list[MissingAnswer], proposed: list[SheetReview], also_blocked_by: str = ""
) -> BuildResult:
    detail = "; ".join(answer.key for answer in missing)
    if also_blocked_by:
        detail += f". Also: {also_blocked_by}"
    return BuildResult("needs_decision", detail, missing_answers=missing, sheets=proposed)


@dataclass
class _Mapping:
    proposals: list[map_terms.MappingProposal]
    reason: str
    answers: dict[str, Answer]

    def source_of(self, term: str) -> str:
        return next((p.source_column for p in self.proposals if p.target == term), "")

    def terms_of_sources(self) -> dict[str, str]:
        return {
            p.source_column: p.target
            for p in self.proposals
            if p.target and p.target not in map_terms.FOLDED_TARGETS
        }


@dataclass
class _Taxonomy:
    table: Table
    taxa: dict[str, dict[str, str]]
    reason: str
    source_names: dict[str, set[str]]


def _require_named_columns(root: Path, table: Table, answers: Answers) -> None:
    table_columns = set(table.columns)
    named = {
        "filters.occurrence_type_col": answers.filters.occurrence_type_col,
        "derive_fields.timestamp_col_a": answers.derive_fields.timestamp_col_a,
        "derive_fields.timestamp_col_b": answers.derive_fields.timestamp_col_b,
    }
    absent = [
        f"{key}: {column!r} is not a column of {artifacts.INTERMEDIATE}"
        for key, column in named.items()
        if column and column not in table_columns
    ]
    if answers.filters.sample_metadata and answers.filters.sample_type_col:
        metadata_columns = set(tsv.read_header(root / answers.filters.sample_metadata))
        if answers.filters.sample_type_col not in metadata_columns:
            absent.append(
                f"filters.sample_type_col: {answers.filters.sample_type_col!r} is not a column of "
                f"{answers.filters.sample_metadata}"
            )
        if not metadata_columns & set(filter_controls.SAMPLE_ID_COLUMNS):
            absent.append(
                f"filters.sample_metadata: {answers.filters.sample_metadata} has no sampleID or "
                "sample_id column. Rename its sample ID column to sampleID"
            )
    if absent:
        raise answers_file.AnswersError("; ".join(absent))


def _read_sample_types(root: Path, answers: Answers) -> dict[str, str]:
    metadata, type_column = answers.filters.sample_metadata, answers.filters.sample_type_col
    if not (metadata and type_column):
        return {}
    id_columns = filter_controls.SAMPLE_ID_COLUMNS
    return {
        next(row[key] for key in id_columns if key in row): row[type_column]
        for row in tsv.read_rows(root / metadata)
    }


def _classify_samples(
    root: Path, table: Table, answers: Answers, findings: FindingsLog
) -> list[dict[str, str]]:
    classified = classify_samples.classify(
        table,
        control_answers=answers.controls,
        sample_types=_read_sample_types(root, answers),
        occurrence_type_col=answers.filters.occurrence_type_col,
    )
    tsv.write_tsv(classified.proposal, root / CONTROL_ROSTER.proposal)
    _take(findings, classified.findings, "classify-samples")
    return classified.roster


def _propose_mapping(
    root: Path, table: Table, units: dict[str, tuple[str, str]], findings: FindingsLog
) -> _Mapping:
    header = read_tab_separated_header(root / artifacts.INTERMEDIATE)
    columns = [column for column in header if column not in CONSUMED_COLUMNS]
    confirmed = sheets.confirmed_mapping(root)
    settled = frozenset(row.source_column for row in confirmed)
    proposed, log = map_terms.propose_mapping(
        columns, TERM_TABLE, written_later=frozenset(JOINED_FIELDS), settled=settled
    )
    unmapped = [p.source_column for p in proposed if p.basis == "unmapped"]
    measured = emof.measurement_columns(table, unmapped)
    map_terms.propose_measurements(proposed, emof.describe_measurements(table, measured, units))
    moving = list(measured)
    (root / TERM_MAPPING.proposal).write_text(
        map_terms.write_mapping_tsv(proposed), encoding="utf-8"
    )
    log.findings.extend(map_terms.review_findings(proposed, settled).findings)
    _take(findings, log, "map-terms")
    applied, unmatched = sheets.apply_confirmed_mapping(proposed, confirmed, header)
    _take(findings, unmatched, "map-terms")
    return _Mapping(
        applied,
        sheets.mapping_reason(log, len(unmapped), moving),
        {
            row.source_column: Answer(None, row.provenance, row.confirmed)
            for row in applied
            if row.provenance
        },
    )


def _join_taxonomy(
    root: Path, table: Table, table_markers: set[str], answers: Answers, findings: FindingsLog
) -> _Taxonomy:
    lineage = derive_lineage.derive_lineage(table, scopes=answers.taxonomy_scopes(table_markers))
    try:
        locked = lock.read(root, lineage.lineage_rows, answers)
    except lock.StaleLock as error:
        raise _Halt("error", str(error)) from error
    shutil.copyfile(root / artifacts.RESOLVED_TAXONOMY, root / TAXA.proposal)
    resolution = resolve_taxonomy.lock_findings(locked)
    _take(findings, resolution, "resolve-taxonomy")
    taxa, log = join_taxonomy.taxa_for_join(
        locked, sheets.confirmed_rows(root, TAXA), confirmed_source=TAXA.confirmed
    )
    _take(findings, log, "join-taxonomy")
    joined = join_taxonomy.join_taxonomy(lineage.occurrences, taxa)
    table = joined.settled("taxonomy", required=REQUIRED_COLUMNS)
    return _Taxonomy(table, taxa, sheets.taxa_reason(locked, resolution), lineage.source_names)


def _excluded_kingdoms_by_marker(
    answers: Answers, table_markers: set[str]
) -> dict[str, set[str]] | None:
    requested = set(answers.filters.exclude_kingdoms)
    if not requested:
        return None
    return {
        marker: requested - target_kingdoms(target.target)
        for marker, target in answers.marker_targets(table_markers).items()
    }


def _exclude(
    root: Path,
    taxonomy: _Taxonomy,
    humans: Table,
    roster: list[dict[str, str]],
    answers: Answers,
    table_markers: set[str],
    findings: FindingsLog,
) -> exclude_taxa.Exclusion:
    table = taxonomy.table
    excluded = exclude_taxa.exclude(
        table,
        controls=filter_controls.control_samples(table.con, roster),
        humans=humans,
        drop_human=bool(answers.filters.exclude_human),
        excluded_kingdoms_by_marker=_excluded_kingdoms_by_marker(answers, table_markers),
        excluded_taxa_by_marker={
            marker: target.exclude_taxa
            for marker, target in answers.marker_targets(table_markers).items()
            if target.exclude_taxa
        },
        source_names=taxonomy.source_names,
        human_answer_confirmed="filters.exclude_human" not in answers.unconfirmed,
    )
    columns = sorted([*table.columns, "exclusion_reason"]) if excluded.excluded.count() else []
    write_tsv(
        excluded.excluded,
        root / artifacts.EXCLUDED_ROWS_REPORT,
        columns,
        order=(exclude_taxa.STEP, ROW),
    )
    _take(findings, excluded.findings, "filter-controls")
    return excluded


def _check_source_columns(
    kept: Table, mapping: _Mapping, answers: Answers, findings: FindingsLog
) -> Table:
    _take(
        findings,
        derive_fields.check_zero_counts(kept, answers.derive_fields.emit_absences),
        "derive-fields",
    )
    _take(
        findings,
        synthesize_ids.check_sequence_columns(kept, mapping.source_of("DNA_sequence")),
        "synthesize-ids",
    )
    col_a, col_b = answers.derive_fields.timestamp_col_a, answers.derive_fields.timestamp_col_b
    if not (col_a and col_b):
        return kept
    timestamped, log = derive_fields.resolve_conflicting_timestamps(
        kept, "source", col_a=col_a, col_b=col_b
    )
    _take(findings, log, "derive-fields")
    return timestamped


def _map_terms(
    table: Table,
    mapping: _Mapping,
    answers: Answers,
    table_markers: set[str],
    findings: FindingsLog,
) -> map_terms.AppliedMapping:
    marker_constants = {
        marker: target.constants
        for marker, target in answers.marker_targets(table_markers).items()
        if target.constants
    }
    replaced_by_the_join = set(JOINED_FIELDS)
    applied = map_terms.apply(
        table,
        [p for p in mapping.proposals if p.source_column not in replaced_by_the_join],
        TERM_TABLE,
        constants=answers.constants,
        marker_constants=marker_constants,
        carried=CARRIED_COLUMNS,
    )
    _take(findings, applied.findings, "map-terms")
    applied.table = applied.table.settled("mapped_settled", keep=applied.hidden())
    return applied


def _derive(
    root: Path,
    applied: map_terms.AppliedMapping,
    excluded: Table,
    mapping: _Mapping,
    quantity_types: dict[str, str],
    findings: FindingsLog,
) -> derive_fields.DerivedFields:
    derived = derive_fields.derive(
        applied.table,
        derive_fields.Derivation(excluded=excluded, quantity_types=quantity_types),
        sheets.confirmed_table(root, DERIVED_VALUES, applied.table.con),
        mapping.terms_of_sources(),
    )
    write_tsv(derived.proposal, root / DERIVED_VALUES.proposal, sorted(derived.proposal.present()))
    _take(findings, derived.findings, "derive-fields")
    return derived


def _publish(
    root: Path,
    applied: map_terms.AppliedMapping,
    derived: derive_fields.DerivedFields,
    answers: Answers,
    findings: FindingsLog,
) -> map_terms.AppliedMapping:
    ids = synthesize_ids.synthesize_ids(derived.table, dataset_id=answers.dataset_id)
    _take(findings, ids.findings, "synthesize-ids")
    with_ids = ids.table.settled("with_ids_settled", keep=applied.dynamic.hidden())
    added = set(with_ids.columns) - set(applied.table.columns)
    formatted, log = map_terms.convert_formats(with_ids, added | derived.corrected, TERM_TABLE)
    _take(findings, log, "map-terms")
    published = formatted.save(
        "published", f"SELECT {formatted.star(*WORKING_COLUMNS)} FROM {formatted.name}"
    )
    proposals = map_terms.review_order(
        map_terms.with_derived_rows(applied.proposals, added, TERM_TABLE)
    )
    (root / artifacts.MAPPING).write_text(map_terms.write_mapping_tsv(proposals), encoding="utf-8")
    return map_terms.AppliedMapping(
        published,
        proposals,
        FindingsLog(applied.findings.findings + log.findings),
        applied.dynamic,
    )


def _state_terms(
    root: Path, applied: map_terms.AppliedMapping, answers: Answers, findings: FindingsLog
) -> list[term_states.TermState]:
    states, log = term_states.state_terms(
        TERM_TABLE,
        applied.proposals,
        applied.table,
        assay_type=answers.term_states.assay_type,
        not_applicable=answers.term_states.not_applicable,
        ask=answers.term_states.ask,
        impossible=answers.term_states.impossible,
    )
    term_states.write_term_states_tsv(states, root / artifacts.TERM_STATES)
    _take(findings, log, "term-states")
    return states


def _write_and_validate(
    root: Path,
    applied: map_terms.AppliedMapping,
    answers: Answers,
    findings: FindingsLog,
    *,
    intermediate_rows: int,
    excluded_rows: int,
) -> writer.WrittenArchive:
    core, proposals = applied.table, applied.proposals
    try:
        written = writer.write_archive_from_table(
            core=core,
            core_header=sorted([*core.columns, emof.DYNAMIC_PROPERTIES_COLUMN]),
            extensions={},
            manifest=answers.metadata,
            dataset_id=answers.dataset_id,
            generated_at=answers.created,
            term_table=TERM_TABLE,
            out_dir=root / answers.out_dir,
            mixs_uri_style=answers.build.mixs_uri_style,
            no_dna_extension=answers.build.no_dna_extension,
            no_emof=answers.build.no_emof,
            units=answers.units,
            measured=map_terms.routed_to(proposals, emof.EMOF_TARGET),
            dynamic=applied.dynamic,
            exclusions=_messages(findings, derive_fields.EXCLUSION_CODES),
        )
        validation = validate.check(
            archive_dir=root / answers.out_dir,
            term_table=TERM_TABLE,
            strict=True,
            intermediate_row_count=intermediate_rows,
            excluded_row_count=excluded_rows,
            obis=True,
            adjudications=answers.adjudications,
            connection=core.con,
            tables=written.tables,
        )
    except (writer.ArchiveBuildError, EmlRenderError) as error:
        raise _Halt("error", f"the archive could not be written: {error}") from error
    findings.findings.extend(written.findings.findings)
    findings.findings.extend(validation.findings)
    return written


def _adjudicate(findings: FindingsLog, answers: Answers) -> None:
    settled = set() if "filters.exclude_human" in answers.unconfirmed else {"HUMAN_PUBLISHED"}
    judged = JUDGED_BY_A_PERSON - settled
    for finding in [f for f in findings.findings if f.code in judged]:
        code = finding.code
        if answers.adjudications.get(code) == "accepted":
            findings.add(
                "STRUCTURAL_COST_DISCLOSED",
                f"{code}: accepted under adjudications: in {artifacts.ANSWERS}, so the archive "
                f"ships as it is: {finding.message}",
                count=finding.count,
            )
        else:
            findings.add(
                ADJUDICATION_NEEDED,
                f"{code}: {finding.message}. This changes what the archive publishes, so a "
                f"person decides: if the archive is right as it is, add {code}: {{status: "
                "accepted, provenance: <why>, confirmed: <the person's reply>} under "
                f"adjudications: in {artifacts.ANSWERS}; otherwise fix what it names and "
                "build again",
                count=finding.count,
            )


def _status(result: BuildResult, findings: FindingsLog) -> tuple[str, str]:
    if errors := _describe_errors(findings):
        return "error", errors
    if not result.waiting:
        return "ok", ""
    return "needs_review", _waiting_detail(result)


def _waiting_detail(result: BuildResult) -> str:
    waiting = [
        f"{review.sheet.proposal.as_posix()}: {review.reason}" for review in result.open_sheets
    ]
    waiting += [f"metadata.{name}: blank" for name in result.blank_metadata]
    if not result.automatic and result.unconfirmed_count:
        waiting.append(
            sheets.describe_unconfirmed(
                result.unconfirmed, result.unconfirmed_sheet_rows, result.unconfirmed_count
            )
        )
    waiting += [f"adjudications: {message}" for message in result.adjudications_needed]
    return "; ".join(waiting)


def _package(
    root: Path, source: Table, answers: Answers, *, automatic: bool, findings: FindingsLog
) -> BuildResult:
    _require_named_columns(root, source, answers)
    table_markers = markers(source)
    roster = _classify_samples(root, source, answers, findings)
    reviews = [SheetReview(CONTROL_ROSTER, sheets.controls_reason(roster), confirmed=False)]
    ambiguous = [row["sampleID"] for row in roster if row.get("action") == "ambiguous"]
    missing = questions.missing_answers(answers, table_markers, ambiguous)
    quantity_types = _constant_by_marker(answers, table_markers, QUANTITY_TYPE)
    missing += questions.quantity_questions(source, quantity_types)
    try:
        mapping = _propose_mapping(root, source, answers.units, findings)
        reviews.append(
            SheetReview(
                TERM_MAPPING,
                mapping.reason,
                (root / TERM_MAPPING.confirmed).exists(),
                sheets.RowsChanged.of(mapping.answers),
            )
        )
        taxonomy = _join_taxonomy(root, source, table_markers, answers, findings)
        reviews.append(
            SheetReview(
                TAXA,
                taxonomy.reason,
                (root / TAXA.confirmed).exists(),
                sheets.RowsChanged.of(join_taxonomy.confirmed_answers(taxonomy.taxa)),
            )
        )
    except (_Halt, sheets.SheetRefused) as stop:
        if missing:
            return _needs_decision(missing, reviews, also_blocked_by=str(stop))
        raise
    humans = exclude_taxa.human_taxa(taxonomy.table)
    if answers.filters.exclude_human is None and (
        human := questions.human_question(taxonomy.table, humans, quantity_types)
    ):
        missing.append(human)
    if missing:
        return _needs_decision(missing, reviews)
    kept = _exclude(root, taxonomy, humans, roster, answers, table_markers, findings)
    checked = _check_source_columns(kept.kept, mapping, answers, findings)
    mapped = _map_terms(checked, mapping, answers, table_markers, findings)
    derived = _derive(root, mapped, kept.excluded, mapping, quantity_types, findings)
    applied = _publish(root, mapped, derived, answers, findings)
    states = _state_terms(root, applied, answers, findings)
    _take(findings, join_taxonomy.check_published_taxa(applied.table, taxonomy.taxa), "check-taxa")
    written = _write_and_validate(
        root,
        applied,
        answers,
        findings,
        intermediate_rows=source.count(),
        excluded_rows=kept.excluded.count(),
    )
    _adjudicate(findings, answers)

    reviews.append(
        SheetReview(
            DERIVED_VALUES,
            sheets.derived_reason(
                FindingsLog(derived.findings.findings + applied.findings.findings)
            ),
            (root / DERIVED_VALUES.confirmed).exists(),
            derived.rows,
        )
    )
    findings.findings.extend(sheets.record_reviews(reviews, automatic=automatic).findings)
    result = BuildResult(
        "",
        "",
        archive_dir=answers.out_dir,
        sheets=reviews,
        blank_metadata=answers.metadata.blank_required(),
        unconfirmed=answers.unconfirmed,
        adjudications_needed=_messages(findings, {ADJUDICATION_NEEDED}),
        missing_eml_elements=missing_profile_elements(answers.metadata),
        automatic=automatic,
    )
    if automatic and result.unconfirmed_count:
        findings.add(
            "UNCONFIRMED_ACCEPTED",
            f"{result.unconfirmed_count} answer(s) no person confirmed were used as written: "
            f"{', '.join([*result.unconfirmed, *result.unconfirmed_sheet_rows])}",
            count=result.unconfirmed_count,
        )
    collected = _bundle(root, answers, findings)
    result.status, result.detail = _status(result, findings)
    _write_report(root, answers, result, written, states, findings)
    bundle.write(collected, root / answers.out_dir)
    return result


def _bundle(root: Path, answers: Answers, findings: FindingsLog) -> bundle.BundleResult:
    collected = bundle.collect(
        root,
        justfile_path=JUSTFILE_TEMPLATE,
        raw_inputs=bundle.recorded_raw_inputs(root / artifacts.CONFIG),
        config_inputs=answers.referenced_inputs(),
    )
    collected.log.findings.extend(bundle.check_declared_tables(root / answers.out_dir).findings)
    findings.findings.extend(collected.log.findings)
    return collected


def _write_report(
    root: Path,
    answers: Answers,
    result: BuildResult,
    written: writer.WrittenArchive,
    states: list[term_states.TermState],
    findings: FindingsLog,
) -> None:
    core = written.tables[writer.FILENAME_BY_KEY["occurrence"]]
    record_count, sample_count = validate.record_and_sample_counts(core, core.columns)
    report.write(
        archive_dir=root / answers.out_dir,
        archive_name=answers.out_dir,
        findings=_recorded(result, findings),
        metadata=answers.metadata,
        open_sheets=len(result.open_sheets),
        blank_metadata=result.blank_metadata,
        missing_eml_elements=result.missing_eml_elements,
        unconfirmed=result.unconfirmed_count,
        audit=audit.load_recorded_audit(
            root / artifacts.AUDIT_RECORD, archive_dir=root / answers.out_dir
        ),
        states=states,
        record_count=record_count,
        sample_count=sample_count,
    )


def build(conversion_dir: Path, *, automatic: bool = False) -> BuildResult:
    _require_writable_directories(conversion_dir)
    environment.record_environment(
        conversion_dir / artifacts.CONFIG, environment.capture_current_environment()
    )
    findings = FindingsLog()
    try:
        answers = answers_file.load(conversion_dir / artifacts.ANSWERS)
        archive_dir.empty(
            conversion_dir,
            answers.out_dir,
            inputs=bundle.recorded_raw_inputs(conversion_dir / artifacts.CONFIG)
            + answers.referenced_inputs(),
        )
    except answers_file.AnswersError as error:
        archive_dir.withdraw(
            conversion_dir, answers_file.declared_out_dir(conversion_dir / artifacts.ANSWERS)
        )
        return _concluded(conversion_dir, BuildResult("error", str(error), refused=True), findings)
    _fresh(conversion_dir / artifacts.PROPOSED_DIR)

    try:
        require_intermediate(conversion_dir / artifacts.INTERMEDIATE)
        findings.findings.extend(
            assemble.recorded_findings(
                conversion_dir / artifacts.ASSEMBLY, conversion_dir / artifacts.INTERMEDIATE
            ).findings
        )
        with connect() as con:
            source = require_valid(conversion_dir / artifacts.INTERMEDIATE, con)
            result = _package(
                conversion_dir, source, answers, automatic=automatic, findings=findings
            )
    except (
        IntermediateMissing,
        IntermediateInvalid,
        sheets.SheetRefused,
        answers_file.AnswersError,
    ) as error:
        result = BuildResult("error", str(error), refused=True)
    except (join_taxonomy.JoinAuditError, term_states.TermSpecError, FileNotFoundError) as error:
        result = BuildResult("error", str(error))
    except _Halt as halt:
        result = BuildResult(halt.status, halt.detail)
    except ResourceLimitError:
        archive_dir.remove(conversion_dir / answers.out_dir)
        raise
    if not result.unconfirmed:
        result.unconfirmed = answers.unconfirmed
    if result.status == "error":
        result.archive_dir = None
    if result.archive_dir is None:
        archive_dir.remove(conversion_dir / answers.out_dir)
    return _concluded(conversion_dir, result, findings)


def _concluded(conversion_dir: Path, result: BuildResult, findings: FindingsLog) -> BuildResult:
    result.findings = _recorded(result, findings)
    (conversion_dir / artifacts.FINDINGS).write_text(
        json.dumps(result.findings, indent=2), encoding="utf-8"
    )
    result.stage = stages.build_stage(conversion_dir)
    review_page.write(result, conversion_dir)
    return result
