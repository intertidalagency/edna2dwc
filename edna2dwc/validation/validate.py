from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import duckdb
import yaml

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.result import CommandResult, render_findings
from edna2dwc.common.table import (
    ROW,
    Table,
    connected,
    in_file_order,
    lookup,
    matching,
    read_tsv,
)
from edna2dwc.common.tsv import read_header
from edna2dwc.conversion import artifacts
from edna2dwc.conversion.answers import AdjudicationsError, parse_adjudications
from edna2dwc.dwca import dna_derived_data, writer
from edna2dwc.dwca.writer import check_columns_are_darwin_core
from edna2dwc.terms import formats
from edna2dwc.terms.country_code import valid_country_codes
from edna2dwc.terms.formats import VOCABULARY_BY_TERM
from edna2dwc.validation import obis_validator
from edna2dwc.validation.gbif_validator import GbifValidation

DWC_TEXT_NS = "http://rs.tdwg.org/dwc/text/"


@dataclass(frozen=True)
class ParsedTable:
    is_core: bool
    row_type: str
    file_location: str
    id_index: int
    field_indices: dict[int, str]


class ArchiveInvalidError(ValueError):
    pass


def resolve_core_file_location(archive_dir: Path) -> str | None:
    meta_path = archive_dir / "meta.xml"
    if not meta_path.exists():
        return None
    for table in parse_meta_xml(meta_path):
        if table.is_core:
            return table.file_location
    return None


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def parse_meta_xml(path: Path) -> list[ParsedTable]:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        raise ArchiveInvalidError(f"meta.xml is not well-formed XML: {exc}") from None

    tables = []
    for table_el in root:
        tag = _local_tag(table_el)
        if tag not in ("core", "extension"):
            continue
        location_el = table_el.find(f"{{{DWC_TEXT_NS}}}files/{{{DWC_TEXT_NS}}}location")
        location = (location_el.text or "").strip() if location_el is not None else ""
        if not location:
            raise ArchiveInvalidError(f"meta.xml <{tag}> has no <files><location>")
        id_tag = "id" if tag == "core" else "coreid"
        id_el = table_el.find(f"{{{DWC_TEXT_NS}}}{id_tag}")
        id_index = id_el.get("index") if id_el is not None else None
        if id_index is None:
            raise ArchiveInvalidError(f"meta.xml <{tag}> has no <{id_tag} index=.../>")
        field_indices = {}
        for field_el in table_el.findall(f"{{{DWC_TEXT_NS}}}field"):
            index = field_el.get("index")
            term = field_el.get("term")
            if index is not None and term is not None:
                field_indices[int(index)] = term
        tables.append(
            ParsedTable(
                is_core=(tag == "core"),
                row_type=table_el.get("rowType", ""),
                file_location=location,
                id_index=int(id_index),
                field_indices=field_indices,
            )
        )
    return tables


def check_field_indices_match_header(
    table: ParsedTable, header: list[str], term_table: dict
) -> FindingsLog:
    log = FindingsLog()
    uri_to_name = {entry["uri"]: name for name, entry in term_table.items() if "uri" in entry}
    for index, uri in table.field_indices.items():
        expected_name = uri_to_name.get(uri, uri)
        actual_name = header[index] if 0 <= index < len(header) else None
        if actual_name != expected_name:
            log.add(
                "META_INDEX_MISMATCH",
                f"{table.file_location}: <field index={index!r}> declares {expected_name!r}, "
                f"but the header has {actual_name!r} there",
            )
    return log


def check_row_shape(
    file_location: str, path: Path, header: list[str], con: duckdb.DuckDBPyConnection
) -> FindingsLog:
    log = FindingsLog()
    lines = (
        "read_csv(?, delim='\x01', header=false, skip=1, quote='', escape='', "
        "columns={'line': 'VARCHAR'}, auto_detect=false, strict_mode=false)"
    )
    misshapen = (
        f"line IS NOT NULL AND length(line) - length(replace(line, '\t', '')) + 1 <> {len(header)}"
    )
    misshapen_rows = con.execute(
        f"SELECT count(*) FROM {lines} WHERE {misshapen}", [str(path)]
    ).fetchone()
    if not misshapen_rows or not misshapen_rows[0]:
        return log
    with in_file_order(con):
        con.execute(
            f"CREATE OR REPLACE TABLE shape_lines AS SELECT line FROM {lines}", [str(path)]
        )
    numbered = Table(con, "shape_lines").view(
        "shape_rows", f"SELECT rowid AS {ROW}, line FROM shape_lines"
    )
    count, rows = numbered.first(f"{ROW} + 2", misshapen)
    log.add(
        "ARCHIVE_INVALID",
        f"{file_location}: {count} row(s) have a field count that does not match the "
        f"header, such as row(s) {_listed(rows)}",
        count=count,
    )
    return log


def _listed(values: list) -> str:
    return ", ".join(str(value) for value in values)


def check_duplicate_ids(file_location: str, id_column: str, table: Table) -> FindingsLog:
    log = FindingsLog()
    value = table.text(id_column)
    for (duplicated,) in table.rows(
        f"SELECT {value} FROM {table.name} GROUP BY 1 HAVING count(*) > 1 "
        f"ORDER BY min_by({ROW}, {ROW}, 2)[2]"
    ):
        log.add("ARCHIVE_INVALID", f"{file_location}: duplicate {id_column} value {duplicated!r}")
    return log


def check_extension_ids_exist_in_core(
    extension_location: str,
    extension: Table,
    core: tuple[Table, str] | None,
    *,
    id_column: str = "occurrenceID",
) -> FindingsLog:
    log = FindingsLog()
    core_ids = (
        f"SELECT {core[0].text(core[1])} FROM {core[0].name}" if core else "SELECT '' WHERE FALSE"
    )
    value = extension.text(id_column)
    count, found = extension.first(value, f"{value} NOT IN ({core_ids})")
    if count:
        log.add(
            "ARCHIVE_INVALID",
            f"{extension_location}: {count} row(s) have an {id_column} with no matching core "
            f"row, such as {_listed([repr(value) for value in found])}",
            count=count,
        )
    return log


def _checkable(header: list[str], term_table: dict) -> list[str]:
    return [name for name in header if term_table.get(name, {}).get("format")]


@dataclass(frozen=True)
class _FormatFailure:
    name: str
    fmt: str
    examples: list[str]
    count: int
    rows: list[int]


def _format_failures(table: Table, header: list[str], term_table: dict) -> list[_FormatFailure]:
    failures = []
    for name in _checkable(header, term_table):
        fmt = term_table[name]["format"]
        value = table.text(name)
        invalid = lookup(
            table,
            "invalid_values",
            [value],
            {"invalid": "BOOLEAN"},
            lambda found, fmt=fmt, name=name: (not _validate_format(fmt, found, name),),
            keep=lambda found, answer: found[0] != "" and answer[0],
        )
        in_invalid = f"EXISTS (SELECT 1 FROM {invalid.name} WHERE {matching(invalid, [value])})"
        count, rows = table.first(f"{ROW} + 2", in_invalid)
        if count:
            examples = table.rows(
                f"SELECT DISTINCT {value} FROM {table.name} WHERE {in_invalid} ORDER BY 1 LIMIT 3"
            )
            failures.append(
                _FormatFailure(name, fmt, [found for (found,) in examples], count, rows)
            )
    return failures


def check_formats(
    file_location: str, header: list[str], table: Table, term_table: dict
) -> FindingsLog:
    log = FindingsLog()
    for failure in _format_failures(table, header, term_table):
        log.add(
            "TERM_FORMAT_INVALID",
            f"{file_location}: {failure.count} row(s) have a {failure.name} that is not "
            f"{formats.describe_format(failure.name, failure.fmt)}, such as {_listed([repr(v) for v in failure.examples])}, "
            f"first in row(s) {_listed(failure.rows)}",
            count=failure.count,
        )
    return log


def count_format_checks(header: list[str], table: Table, term_table: dict) -> tuple[int, int]:
    checkable = _checkable(header, term_table)
    if not checkable:
        return 0, 0
    (checked,) = table.one(
        "SELECT "
        + " + ".join(f"count(*) FILTER (WHERE {table.text(name)} <> '')" for name in checkable)
        + f" FROM {table.name}"
    )
    failures = _format_failures(table, header, term_table)
    return checked, sum(failure.count for failure in failures)


def _validate_format(fmt: str, value: str, term_name: str) -> bool:
    if fmt == "iso8601_date":
        return formats.validate_iso8601_date(value)
    if fmt == "decimal_degrees":
        max_abs = 90.0 if "latitude" in term_name.lower() else 180.0
        return formats.validate_decimal_degrees(value, max_abs=max_abs)
    if fmt == "iso3166_alpha2":
        return formats.validate_iso3166_alpha2(value, valid_codes=valid_country_codes())
    if fmt == "controlled":
        return formats.validate_controlled(value, vocabulary=VOCABULARY_BY_TERM.get(term_name))
    if fmt == "nonneg_number":
        return formats.validate_nonneg_number(value)
    if fmt == "number_with_unit":
        return formats.validate_number_with_unit(value)
    if fmt == "uri":
        return formats.validate_uri(value)
    if fmt == "wkt":
        return formats.validate_wkt(value)
    if fmt == "dna_sequence":
        return formats.validate_dna_sequence(value)
    if fmt == "pipe_list":
        return formats.validate_pipe_list(value)
    return True


def check_pairs_and_expects(
    file_location: str,
    header: list[str],
    table: Table,
    term_table: dict,
    *,
    is_occurrence_core: bool = True,
) -> FindingsLog:
    log = FindingsLog()
    header_set = set(header)
    pair_rules: list[tuple[str, str, str]] = []
    for name in header:
        entry = term_table.get(name, {})
        for pair in entry.get("pairs", []):
            if pair.get("scope") == "occurrence_core_only" and not is_occurrence_core:
                continue
            pair_rules.append((name, pair["with"], pair["severity"]))
        for expectation in entry.get("expects", []):
            if expectation.get("scope") == "occurrence_core_only" and not is_occurrence_core:
                continue
            pair_rules.append((name, expectation["then"], expectation["severity"]))

    for first, second, severity in pair_rules:
        incomplete, rows = table.first(
            f"{ROW} + 2", f"{table.text(first)} <> '' AND {table.text(second)} = ''"
        )
        if incomplete:
            state = "is not" if second in header_set else "has no column in this table"
            log.add(
                "TERM_PAIR_INCOMPLETE",
                f"{file_location}: {incomplete} row(s) have {first!r} populated but "
                f"{second!r} {state}, such as row(s) {', '.join(str(row) for row in rows)}",
                severity=severity,
                count=incomplete,
            )
    return log


PRIORITY_TIERS = ("required", "strongly_recommended")


@dataclass(frozen=True)
class MissingTerm:
    term: str
    tier: str
    filled: int
    total: int

    @property
    def share(self) -> str:
        return f"{self.filled} of {self.total} rows"


Fill = dict[str, tuple[int, int]]


def listed_priority_terms(term_table: dict) -> list[str]:
    return [
        name
        for name, entry in sorted(term_table.items())
        if entry.get("priority_tier") in PRIORITY_TIERS
    ]


def term_fill(tables: list[tuple[list[str], Table]], term_table: dict) -> Fill:
    fill: Fill = {}
    counted = [(header, table, table.count()) for header, table in tables]
    core_rows = counted[0][2] if counted else 0
    for term in listed_priority_terms(term_table):
        fill[term] = (0, core_rows)
        for header, table, total in counted:
            if term in header:
                fill[term] = (table.count(f"{table.text(term)} <> ''"), total)
                break
    return fill


def unfilled_priority_terms(
    fill: Fill, term_table: dict, *, excused_terms: set[str] | None = None
) -> list[MissingTerm]:
    return [
        MissingTerm(term, term_table[term]["priority_tier"], *fill.get(term, (0, 0)))
        for term in listed_priority_terms(term_table)
        if term not in (excused_terms or set()) and _unfilled(fill.get(term, (0, 0)))
    ]


def _unfilled(counts: tuple[int, int]) -> bool:
    filled, total = counts
    return filled < total or total == 0


def check_priority_required_terms(
    fill: Fill, term_table: dict, *, not_applicable_terms: set[str] | None = None
) -> FindingsLog:
    log = FindingsLog()
    for missing in unfilled_priority_terms(fill, term_table, excused_terms=not_applicable_terms):
        code = (
            "TERM_MISSING_PRIORITY" if missing.tier == "required" else "TERM_MISSING_RECOMMENDED"
        )
        log.add(code, f"{missing.term!r} is filled on {missing.share}")
    return log


def check_core_carries_no_dna_terms(
    file_location: str, header: list[str], term_table: dict
) -> FindingsLog:
    log = FindingsLog()
    in_core = dna_derived_data.select_dna_columns(header, term_table)
    if in_core:
        log.add(
            "DNA_TERMS_IN_CORE",
            f"{file_location} has {dna_derived_data.TERM_CLASS}-classed column(s) that "
            f"belong in {writer.FILENAME_BY_KEY[writer.DNA_KEY]}: {', '.join(in_core)}",
            count=len(in_core),
        )
    return log


def load_adjudications(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not data:
        return {}
    if "adjudications" not in data:
        raise AdjudicationsError(
            f"{path} has no top-level 'adjudications:' key. Each issue class goes under it, "
            "with a 'status' of accepted or rejected, its 'provenance' and the person's reply in 'confirmed'."
        )
    return parse_adjudications(data["adjudications"], str(path))


def record_and_sample_counts(core: Table, header: list[str]) -> tuple[int, int | None]:
    sample = core.text("materialSampleID")
    records, samples = core.one(
        f"SELECT count(*), count(DISTINCT {sample}) FILTER (WHERE {sample} <> '') FROM {core.name}"
    )
    return records, samples if "materialSampleID" in header else None


def check_row_accounting(
    *, intermediate_row_count: int, archive_row_count: int, excluded_row_count: int
) -> FindingsLog:
    log = FindingsLog()
    if archive_row_count + excluded_row_count != intermediate_row_count:
        log.add(
            "ROW_ACCOUNTING_MISMATCH",
            f"intermediate rows ({intermediate_row_count}) != archive rows "
            f"({archive_row_count}) + documented exclusions ({excluded_row_count})",
        )
    return log


def validate_archive(
    archive_dir: Path,
    term_table: dict,
    *,
    strict: bool = False,
    priority_terms: bool = False,
    intermediate_row_count: int | None = None,
    excluded_row_count: int = 0,
    connection: duckdb.DuckDBPyConnection | None = None,
    tables: Mapping[str, Table] | None = None,
) -> FindingsLog:
    findings = FindingsLog()
    tables = tables or {}

    eml_path = archive_dir / "eml.xml"
    if not eml_path.exists():
        raise ArchiveInvalidError("eml.xml is missing")
    try:
        ET.fromstring(eml_path.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        raise ArchiveInvalidError(f"eml.xml is not well-formed XML: {exc}") from None

    meta_path = archive_dir / "meta.xml"
    if not meta_path.exists():
        raise ArchiveInvalidError("meta.xml is missing")
    declared = sorted(parse_meta_xml(meta_path), key=lambda t: not t.is_core)

    read: list[tuple[list[str], Table]] = []
    core: tuple[Table, str] | None = None
    archive_row_count = 0

    with connected(connection) as con:
        for i, table in enumerate(declared):
            table_path = archive_dir / table.file_location
            if not table_path.exists():
                raise ArchiveInvalidError(
                    f"{table.file_location} is declared in meta.xml but missing"
                )
            header = list(read_header(table_path, delimiter="\t"))
            findings.findings.extend(
                check_field_indices_match_header(table, header, term_table).findings
            )
            findings.findings.extend(
                check_row_shape(table.file_location, table_path, header, con).findings
            )
            rows = tables.get(table.file_location) or read_tsv(
                con, table_path, f"archive_table_{i}", header
            )
            read.append((header, rows))

            id_column = header[table.id_index] if 0 <= table.id_index < len(header) else None
            if id_column is None:
                id_tag = "id" if table.is_core else "coreid"
                raise ArchiveInvalidError(
                    f"{table.file_location}: <{id_tag} index={table.id_index!r}> does not point "
                    "at a real column in this table's header"
                )
            if table.is_core:
                core = (rows, id_column)
                archive_row_count = rows.count()
                findings.findings.extend(
                    check_duplicate_ids(table.file_location, id_column, rows).findings
                )
                findings.findings.extend(
                    check_core_carries_no_dna_terms(
                        table.file_location, header, term_table
                    ).findings
                )
            else:
                findings.findings.extend(
                    check_extension_ids_exist_in_core(
                        table.file_location, rows, core, id_column=id_column
                    ).findings
                )

            findings.findings.extend(
                check_formats(table.file_location, header, rows, term_table).findings
            )
            findings.findings.extend(
                check_pairs_and_expects(
                    table.file_location,
                    header,
                    rows,
                    term_table,
                    is_occurrence_core=table.is_core,
                ).findings
            )
            if strict:
                findings.findings.extend(
                    check_columns_are_darwin_core(header, term_table).findings
                )

        if priority_terms:
            findings.findings.extend(
                check_priority_required_terms(term_fill(read, term_table), term_table).findings
            )

    if intermediate_row_count is not None:
        findings.findings.extend(
            check_row_accounting(
                intermediate_row_count=intermediate_row_count,
                archive_row_count=archive_row_count,
                excluded_row_count=excluded_row_count,
            ).findings
        )

    return findings


def step(*, as_json: bool = False, **options: Any) -> CommandResult:
    log = check(**options)
    text = render_findings(log) if log.findings else "Archive is valid."
    return CommandResult.of("validate", log, text=text, as_json=as_json, exits_on_error=True)


def check(
    *,
    archive_dir: Path,
    term_table: dict,
    strict: bool = False,
    priority_terms: bool = False,
    intermediate_path: Path | None = None,
    excluded_report_path: Path | None = None,
    gbif: GbifValidation | None = None,
    obis: bool = False,
    adjudications: Mapping[str, str] | None = None,
    connection: duckdb.DuckDBPyConnection | None = None,
    tables: Mapping[str, Table] | None = None,
    intermediate_row_count: int | None = None,
    excluded_row_count: int = 0,
) -> FindingsLog:
    with connected(connection) as con:
        if intermediate_row_count is None and intermediate_path is not None:
            intermediate_row_count = read_tsv(con, intermediate_path, "intermediate_rows").count()
            if excluded_report_path is not None:
                header = read_header(excluded_report_path, delimiter="\t")
                excluded = read_tsv(con, excluded_report_path, "excluded_rows", header)
                excluded_row_count = excluded.count()
        try:
            log = validate_archive(
                archive_dir,
                term_table,
                strict=strict,
                priority_terms=priority_terms,
                intermediate_row_count=intermediate_row_count,
                excluded_row_count=excluded_row_count,
                connection=con,
                tables=tables,
            )
        except ArchiveInvalidError as exc:
            log = FindingsLog()
            log.add("ARCHIVE_INVALID", str(exc))

        adjudications = dict(adjudications or {})
        if gbif is not None:
            gbif_log, _ = gbif(archive_dir / artifacts.ZIP_NAME, adjudications)
            log.findings.extend(gbif_log.findings)

        if obis:
            log.findings.extend(_run_obis(con, archive_dir, adjudications, tables or {}).findings)
    return log


def _run_obis(
    con: duckdb.DuckDBPyConnection,
    archive_dir: Path,
    adjudications: dict[str, str],
    tables: Mapping[str, Table],
) -> FindingsLog:
    try:
        core_file_location = resolve_core_file_location(archive_dir)
    except ArchiveInvalidError:
        core_file_location = None
    core_path = archive_dir / core_file_location if core_file_location else None
    if core_path is None or not core_path.exists():
        log = FindingsLog()
        log.add(
            "ARCHIVE_INVALID",
            "cannot run --obis: could not resolve the archive's core table from meta.xml",
        )
        return log
    header = read_header(core_path, delimiter="\t")
    core = tables.get(core_file_location or "") or read_tsv(con, core_path, "obis_core", header)
    return obis_validator.run_obis_validation(header, core, adjudications=adjudications)
