from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import Table, read_tsv
from edna2dwc.common.tsv import read_header, read_rows
from edna2dwc.conversion import artifacts
from edna2dwc.dwca import writer
from edna2dwc.terms import map_terms, term_states
from edna2dwc.validation import gbif_validator, obis_validator, validate

Gate = tuple[bool, str]

UNTRACEABLE_BASES = frozenset({"", "unmapped", "ambiguous"})


@dataclass(frozen=True)
class ArchiveTables:
    core_header: list[str]
    core: Table | None
    all_headers: list[list[str]]
    format_checked: int
    format_failed: int
    record_count: int = 0
    sample_count: int | None = None
    fill: validate.Fill = field(default_factory=dict)


@dataclass(frozen=True)
class Gates:
    required_terms: Gate
    strongly_recommended_terms: Gate
    valid_darwin_core_terms: Gate
    mapping_description: Gate | None
    every_term_has_a_state: Gate | None
    row_accounting: Gate | None

    def measured_optional(self) -> dict[str, Gate]:
        optional = {
            "mapping_description": self.mapping_description,
            "every_term_has_a_state": self.every_term_has_a_state,
            "row_accounting": self.row_accounting,
        }
        return {name: gate for name, gate in optional.items() if gate is not None}


@dataclass(frozen=True)
class ValidatorResult:
    ran: bool
    detail: str = ""
    errors: dict[str, int] = field(default_factory=dict)
    error_findings: list = field(default_factory=list)


def read_tables(
    archive_dir: Path, term_table: dict, con: duckdb.DuckDBPyConnection
) -> ArchiveTables:
    core_file_location = validate.resolve_core_file_location(archive_dir)
    if core_file_location is None:
        raise validate.ArchiveInvalidError(
            f"{archive_dir} has no meta.xml, or meta.xml declares no core table"
        )
    core_path = archive_dir / core_file_location
    if not core_path.exists():
        raise validate.ArchiveInvalidError(
            f"meta.xml declares core table {core_file_location!r}, but it is missing"
        )
    core_header = list(read_header(core_path, delimiter="\t"))
    core = read_tsv(con, core_path, "gate_core", core_header)
    read = [(core_header, core)]
    checked, failed = validate.count_format_checks(core_header, core, term_table)
    for i, table in enumerate(validate.parse_meta_xml(archive_dir / "meta.xml")):
        path = archive_dir / table.file_location
        if table.is_core or not path.exists():
            continue
        header = list(read_header(path, delimiter="\t"))
        extension = read_tsv(con, path, f"gate_extension_{i}", header)
        read.append((header, extension))
        table_checked, table_failed = validate.count_format_checks(header, extension, term_table)
        checked += table_checked
        failed += table_failed
    records, samples = validate.record_and_sample_counts(core, core_header)
    return ArchiveTables(
        core_header,
        core,
        [header for header, _ in read],
        checked,
        failed,
        records,
        samples,
        validate.term_fill(read, term_table),
    )


def load_term_states(path: Path | None) -> list[term_states.TermState]:
    if path is None:
        return []
    return [
        term_states.TermState(r["term"], r["state"], r["evidence"])
        for r in read_rows(path, delimiter="\t")
    ]


def count_rows(path: Path | None) -> int | None:
    if path is None:
        return None
    return sum(1 for _ in read_rows(path, delimiter="\t"))


def run_gbif(
    archive_dir: Path, adjudications: dict[str, str], validation: gbif_validator.GbifValidation
) -> ValidatorResult:
    log, issues = validation(archive_dir / artifacts.ZIP_NAME, adjudications)
    unmeasured = [f for f in log.findings if f.code in gbif_validator.NO_VERDICT_CODES]
    if unmeasured:
        return ValidatorResult(ran=False, detail=unmeasured[0].message)
    return ValidatorResult(
        ran=True,
        errors={
            issue.category: issue.affected_records
            for issue in issues
            if issue.severity == "error" and adjudications.get(issue.category) != "accepted"
        },
        error_findings=[f for f in log.findings if f.severity == "error"],
    )


def run_obis(tables: ArchiveTables, adjudications: dict[str, str]) -> ValidatorResult:
    issues: list[str] = []
    assert tables.core is not None
    log = obis_validator.run_obis_validation(
        tables.core_header, tables.core, adjudications=adjudications, issues_out=issues
    )
    errors: dict[str, int] = {}
    for category in issues:
        if adjudications.get(category) != "accepted":
            errors[category] = errors.get(category, 0) + 1
    return ValidatorResult(
        ran=True, errors=errors, error_findings=[f for f in log.findings if f.severity == "error"]
    )


def excused_terms(states: list[term_states.TermState], term_table: dict) -> set[str]:
    return {
        s.term
        for s in states
        if s.state == "Not-applicable" and not term_states.archive_requires(s.term, term_table)
    }


def _terms_gate(missing: list[validate.MissingTerm], tier: str) -> Gate:
    unfilled = [f"{m.term} ({m.filled}/{m.total} rows)" for m in missing if m.tier == tier]
    return (not unfilled, ", ".join(unfilled))


def _darwin_core_gate(tables: ArchiveTables, term_table: dict) -> Gate:
    log = FindingsLog()
    for header in tables.all_headers:
        log.findings.extend(writer.check_columns_are_darwin_core(header, term_table).findings)
    return (not log.findings, "; ".join(f.message for f in log.findings))


def _mapping_gate(mapping_path: Path) -> Gate:
    proposals = map_terms.read_mapping_tsv(mapping_path.read_text(encoding="utf-8"))
    untraceable = [
        p.source_column
        for p in proposals
        if p.target not in ("", "dynamicProperties")
        and p.basis in UNTRACEABLE_BASES
        and not p.provenance
    ]
    return (
        not untraceable,
        f"no traceable mapping method for: {', '.join(untraceable)}" if untraceable else "",
    )


def _row_accounting_gate(
    tables: ArchiveTables, intermediate_path: Path, excluded_report_path: Path | None
) -> Gate:
    log = validate.check_row_accounting(
        intermediate_row_count=count_rows(intermediate_path) or 0,
        archive_row_count=tables.record_count,
        excluded_row_count=count_rows(excluded_report_path) or 0,
    )
    return (not log.findings, "; ".join(f.message for f in log.findings))


def check_gates(
    tables: ArchiveTables,
    term_table: dict,
    *,
    states: list[term_states.TermState],
    mapping_path: Path | None,
    term_states_path: Path | None,
    intermediate_path: Path | None,
    excluded_report_path: Path | None,
) -> Gates:
    missing = validate.unfilled_priority_terms(
        tables.fill, term_table, excused_terms=excused_terms(states, term_table)
    )
    return Gates(
        required_terms=_terms_gate(missing, "required"),
        strongly_recommended_terms=_terms_gate(missing, "strongly_recommended"),
        valid_darwin_core_terms=_darwin_core_gate(tables, term_table),
        mapping_description=_mapping_gate(mapping_path) if mapping_path else None,
        every_term_has_a_state=(
            term_states.check_every_term_has_a_state(states) if term_states_path else None
        ),
        row_accounting=(
            _row_accounting_gate(tables, intermediate_path, excluded_report_path)
            if intermediate_path
            else None
        ),
    )
