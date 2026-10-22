from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from xml.dom import minidom
from xml.etree import ElementTree as ET
import zipfile


EMOF_KEY = "extendedmeasurementorfact"
ROW_TYPE_URIS: dict[str, str] = {
    "occurrence": "http://rs.tdwg.org/dwc/terms/Occurrence",
    "dnaderiveddata": "http://rs.gbif.org/terms/1.0/DNADerivedData",
    "extendedmeasurementorfact": "http://rs.iobis.org/obis/terms/ExtendedMeasurementOrFact",
}
FILENAME_BY_KEY: dict[str, str] = {
    "occurrence": "occurrence.txt",
    "dnaderiveddata": "dnaderiveddata.txt",
    "extendedmeasurementorfact": "extendedmeasurementorfact.txt",
}
CORE_ID_TERM = "occurrenceID"
REQUIRED_CORE_TERMS = ("occurrenceID", "scientificName", "basisOfRecord")


_FIXED_ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)

_MIXS_LEGACY_RE = re.compile(r"^https://w3id\.org/gensc/terms/MIXS:(\d+)$")


class ArchiveBuildError(ValueError):


@dataclass(frozen=True)
class TableSpec:
    key: str


def _row_type_uri(key: str) -> str:
    try:
        return ROW_TYPE_URIS[key]
    except KeyError:
        raise ArchiveBuildError(
            f"{key!r} is not a recognized core/extension key "
            f"(known: {', '.join(sorted(ROW_TYPE_URIS))})"
        ) from None


def check_no_duplicate_row_types(keys: Iterable[str]) -> None:
    seen: dict[str, str] = {}
    for key in keys:
        row_type = _row_type_uri(key)
        if row_type in seen:
            raise ArchiveBuildError(
                "archive can declare each rowType at most once"
            )
        seen[row_type] = key


def check_columns_are_darwin_core(header: Iterable[str], term_table: dict) -> FindingsLog:
    log = FindingsLog()
    for name in header:
        if name not in term_table:
            log.add("TERM_NOT_DARWIN_CORE", f"{name!r} is not a term in dwc_terms.json")
    return log


    try:
        uri = term_table[name]["uri"]
    except KeyError:
        raise ArchiveBuildError(
        ) from None
    if mixs_uri_style == "legacy":
        match = _MIXS_LEGACY_RE.match(uri)
        if match:
            return f"https://w3id.org/mixs/{match.group(1)}"
    return uri


_FULL_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_BARE_YEAR_RE = re.compile(r"\d{4}")


def _calendar_date_safe(value: str) -> str | None:
    if _FULL_DATE_RE.fullmatch(value) or _BARE_YEAR_RE.fullmatch(value):
        return value
    if len(value) > 10 and value[10] in "T " and _FULL_DATE_RE.fullmatch(value[:10]):
        return value[:10]
    return None




        )


_DWC_TEXT_XML_NS = "http://rs.tdwg.org/dwc/text/"
_TABLE_ATTRS = {
    "encoding": "UTF-8",
    "fieldsTerminatedBy": "\\t",
    "linesTerminatedBy": "\\n",
    "fieldsEnclosedBy": "",
    "ignoreHeaderLines": "1",
}


def _build_meta_xml(
    core_header: list[str],
    extensions: list[tuple[TableSpec, list[str]]],
    term_table: dict,
    *,
) -> ET.Element:
    archive_el = ET.Element("archive", {"xmlns": _DWC_TEXT_XML_NS, "metadata": "eml.xml"})

    core_id_index = core_header.index(CORE_ID_TERM)
    core_el = ET.SubElement(
        archive_el, "core", {**_TABLE_ATTRS, "rowType": ROW_TYPE_URIS["occurrence"]}
    )
    files_el = ET.SubElement(core_el, "files")
    ET.SubElement(files_el, "location").text = FILENAME_BY_KEY["occurrence"]
    ET.SubElement(core_el, "id", {"index": str(core_id_index)})
    for i, name in enumerate(core_header):
        uri = _resolve_term_uri(term_table, name, mixs_uri_style=mixs_uri_style)
        ET.SubElement(core_el, "field", {"index": str(i), "term": uri})

    for spec, header in extensions:
        ext_el = ET.SubElement(
            archive_el, "extension", {**_TABLE_ATTRS, "rowType": ROW_TYPE_URIS[spec.key]}
        )
        files_el = ET.SubElement(ext_el, "files")
        ET.SubElement(files_el, "location").text = FILENAME_BY_KEY[spec.key]
        coreid_index = header.index(CORE_ID_TERM)
        ET.SubElement(ext_el, "coreid", {"index": str(coreid_index)})
        for i, name in enumerate(header):
            uri = _resolve_term_uri(term_table, name, mixs_uri_style=mixs_uri_style)
            ET.SubElement(ext_el, "field", {"index": str(i), "term": uri})

    return archive_el


def _pretty_xml_bytes(element: ET.Element) -> bytes:
    rough = ET.tostring(element, encoding="utf-8")
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")


def _write_zip(out_dir: Path, members: list[str]) -> Path:
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name in members:
    return zip_path


    *,
    extensions: dict[str, Path],
    manifest: Manifest,
    dataset_id: str,
    generated_at: str,
    term_table: dict,
    out_dir: Path,
    no_emof: bool = False,
        raise ArchiveBuildError(
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    missing_required = [t for t in REQUIRED_CORE_TERMS if t not in core_header]
    if missing_required:
        raise ArchiveBuildError(
            f"core table is missing build-blocking required term(s): {', '.join(missing_required)}"
        )
    if CORE_ID_TERM not in core_header:
        raise ArchiveBuildError(f"core table has no {CORE_ID_TERM!r} column to key extensions on")

    findings = FindingsLog()
    check_no_duplicate_row_types(["occurrence", *(s.key for s in ext_specs)])

    ext_headers: list[tuple[TableSpec, list[str]]] = []
    for spec in ext_specs:
        if "dynamicProperties" in header:
            raise ArchiveBuildError(
                "dynamicProperties folding is permitted only on the occurrence/event core, "
                "never on an extension"
            )
        if CORE_ID_TERM not in header:
            raise ArchiveBuildError(
                f"{spec.key!r} extension has no {CORE_ID_TERM!r} column to key its coreid on"
            )
        ext_headers.append((spec, header))

    guard_log = check_columns_are_darwin_core(core_header, term_table)
    for _spec, header in ext_headers:
        guard_log.findings.extend(check_columns_are_darwin_core(header, term_table).findings)
    if guard_log.has_errors():
        bad_columns = ", ".join(f.message for f in guard_log.findings)
        raise ArchiveBuildError(f"build refuses non-Darwin-Core column(s): {bad_columns}")



    meta_root = _build_meta_xml(
        core_header, ext_headers, term_table, mixs_uri_style=mixs_uri_style
    )
    (out_dir / "meta.xml").write_bytes(_pretty_xml_bytes(meta_root))
    (out_dir / "eml.xml").write_text(
        render_eml_xml(
            manifest,
            dataset_id=dataset_id,
            generated_at=generated_at,
        ),
        encoding="utf-8",
    )

    members = [FILENAME_BY_KEY["occurrence"], "meta.xml", "eml.xml"]
    members += [FILENAME_BY_KEY[s.key] for s in ext_specs]
    _write_zip(out_dir, members)

