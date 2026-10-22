from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml


DWC_TEXT_NS = "http://rs.tdwg.org/dwc/text/"


@dataclass(frozen=True)
class ParsedTable:
    is_core: bool
    row_type: str
    file_location: str


class ArchiveInvalidError(ValueError):


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
            raise ArchiveInvalidError(f"meta.xml <{tag}> has no <files><location>")
        id_tag = "id" if tag == "core" else "coreid"
        id_el = table_el.find(f"{{{DWC_TEXT_NS}}}{id_tag}")
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


    log = FindingsLog()
    return log


    log = FindingsLog()
    return log


def check_extension_ids_exist_in_core(
    extension_location: str,
    *,
    id_column: str = "occurrenceID",
) -> FindingsLog:
    log = FindingsLog()
    return log


def check_formats(
) -> FindingsLog:
    log = FindingsLog()
    return log


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


def check_pairs_and_expects(
    file_location: str,
    header: list[str],
    term_table: dict,
    *,
    is_occurrence_core: bool = True,
) -> FindingsLog:
    log = FindingsLog()
    header_set = set(header)
    for name in header:
        entry = term_table.get(name, {})
        for pair in entry.get("pairs", []):
            if pair.get("scope") == "occurrence_core_only" and not is_occurrence_core:
                continue
        for expectation in entry.get("expects", []):
            if expectation.get("scope") == "occurrence_core_only" and not is_occurrence_core:
                continue

    return log


    log = FindingsLog()
    return log


    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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
    intermediate_row_count: int | None = None,
    excluded_row_count: int = 0,
) -> FindingsLog:
    findings = FindingsLog()

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

    archive_row_count = 0



            findings.findings.extend(
            )
                ).findings
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
