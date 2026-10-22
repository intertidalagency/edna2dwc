from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
import math
from pathlib import Path
import re
import shutil
from typing import Any, Literal, get_args
from xml.dom import minidom
from xml.etree import ElementTree as ET
import zipfile

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import ROW, Table, column, connect, number_lines, read_tsv, write_lines
from edna2dwc.common.tsv import read_header
from edna2dwc.conversion import artifacts
from edna2dwc.dwca import dna_derived_data, emof
from edna2dwc.dwca.eml import render_eml_xml
from edna2dwc.dwca.manifest import BoundingBox, Manifest
from edna2dwc.taxonomy.unassigned import is_placeholder_taxon
from edna2dwc.terms.dynamic_properties import COLUMN as DYNAMIC_PROPERTIES
from edna2dwc.terms.dynamic_properties import DynamicProperties

DNA_KEY = "dnaderiveddata"
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

MixsUriStyle = Literal["gensc", "legacy"]
MIXS_URI_STYLES = get_args(MixsUriStyle)
_MIXS_LEGACY_RE = re.compile(r"^https://w3id\.org/gensc/terms/MIXS:(\d+)$")


class ArchiveBuildError(ValueError):
    pass


@dataclass(frozen=True)
class TableSpec:
    key: str
    table: Table
    header: tuple[str, ...]
    order: tuple[str, ...] = (ROW,)


@dataclass(frozen=True)
class WrittenArchive:
    findings: FindingsLog
    tables: dict[str, Table]


def _row_type_uri(key: str) -> str:
    try:
        return ROW_TYPE_URIS[key]
    except KeyError:
        raise ArchiveBuildError(
            f"{key!r} is not a recognized core/extension key "
            f"(known: {', '.join(sorted(ROW_TYPE_URIS))})"
        ) from None


def resolve_table_specs(
    core_spec: str, extension_specs: Iterable[str]
) -> tuple[Path, dict[str, Path]]:
    core_key, core_path = _parse_table_spec(core_spec, option_name="--core")
    if core_key != "occurrence":
        raise ArchiveBuildError(f"--core only supports 'occurrence' today, got {core_key!r}")
    extensions: dict[str, Path] = {}
    for raw in extension_specs:
        key, path = _parse_table_spec(raw, option_name="--extension")
        if key in extensions:
            raise ArchiveBuildError(f"--extension {key!r} was given more than once")
        extensions[key] = path
    return core_path, extensions


def _parse_table_spec(raw: str, *, option_name: str) -> tuple[str, Path]:
    key, sep, path_str = raw.partition("=")
    if not sep:
        raise ArchiveBuildError(f"{option_name} {raw!r} must be in TYPE=PATH form")
    return key, Path(path_str)


def check_no_duplicate_row_types(keys: Iterable[str]) -> None:
    seen: dict[str, str] = {}
    for key in keys:
        row_type = _row_type_uri(key)
        if row_type in seen:
            raise ArchiveBuildError(
                f"{seen[row_type]!r} and {key!r} both resolve to rowType {row_type!r}, and an "
                "archive can declare each rowType at most once"
            )
        seen[row_type] = key


def check_columns_are_darwin_core(header: Iterable[str], term_table: dict) -> FindingsLog:
    log = FindingsLog()
    for name in header:
        if name not in term_table:
            log.add("TERM_NOT_DARWIN_CORE", f"{name!r} is not a term in dwc_terms.json")
    return log


def _resolve_term_uri(term_table: dict, name: str, *, mixs_uri_style: MixsUriStyle) -> str:
    try:
        uri = term_table[name]["uri"]
    except KeyError:
        raise ArchiveBuildError(
            f"{name!r} is not a term in the Darwin Core term table, so build has no term URI "
            "for its meta.xml <field>"
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


@dataclass(frozen=True)
class EmlSummary:
    event_date_range: tuple[str, str] | None
    kingdoms: list[str]
    occurrence_statuses: set[str]
    detection_limits: list[str]
    bounding_box: BoundingBox | None


def _coordinate(value: str | None, limit: float) -> float | None:
    try:
        number = float(value or "")
    except ValueError:
        return None
    return number if math.isfinite(number) and abs(number) <= limit else None


def _bounding_box(core: Table) -> BoundingBox | None:
    points = [
        (lat, lon)
        for lat_text, lon_text in core.rows(
            f"SELECT DISTINCT {core.text('decimalLatitude')}, {core.text('decimalLongitude')} "
            f"FROM {core.name}"
        )
        if (lat := _coordinate(lat_text, 90)) is not None
        and (lon := _coordinate(lon_text, 180)) is not None
    ]
    if not points:
        return None
    latitudes, longitudes = zip(*points)
    return BoundingBox(
        west=min(longitudes), south=min(latitudes), east=max(longitudes), north=max(latitudes)
    )


def _first_seen(core: Table, name: str) -> list[str]:
    values = core.rows(f"SELECT {core.text(name)} FROM {core.name} GROUP BY 1 ORDER BY min({ROW})")
    return list(dict.fromkeys(stripped for (value,) in values if (stripped := value.strip())))


def _scan_eml_summary(core: Table) -> EmlSummary:
    event_dates = [
        safe
        for (event_date,) in core.rows(
            f"SELECT DISTINCT {core.text('eventDate')} FROM {core.name}"
        )
        for endpoint in event_date.split("/")
        if event_date and (safe := _calendar_date_safe(endpoint)) is not None
    ]
    kingdoms = [k for k in _first_seen(core, "kingdom") if not is_placeholder_taxon(k)]
    statuses = {
        stripped
        for (status,) in core.rows(
            f"SELECT DISTINCT {core.text('occurrenceStatus')} FROM {core.name}"
        )
        if (stripped := status.strip())
    }
    date_range = (min(event_dates), max(event_dates)) if event_dates else None
    return EmlSummary(
        date_range, kingdoms, statuses, _first_seen(core, "pcr_primer_lod"), _bounding_box(core)
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
    mixs_uri_style: MixsUriStyle,
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
    zip_path = out_dir / artifacts.ZIP_NAME
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name in members:
            member = zipfile.ZipInfo.from_file(out_dir / name, arcname=name)
            member.date_time = _FIXED_ZIP_DATE_TIME
            member.compress_type = zipfile.ZIP_DEFLATED
            with (out_dir / name).open("rb") as source, zf.open(member, "w") as target:
                shutil.copyfileobj(source, target)
    return zip_path


@dataclass(frozen=True)
class PackagedArchive:
    findings: FindingsLog
    measured: list[str]


def write_archive(*, core_path: Path, no_emof: bool = False, **options: Any) -> PackagedArchive:
    with connect() as con:
        core = read_tsv(con, core_path, "core")
        dynamic = DynamicProperties.published_in(core)
        measured = [] if no_emof else emof.dynamic_entries(core, dynamic).keys_that_look_measured()
        written = write_archive_from_table(
            core=core,
            core_header=read_header(core_path, delimiter="\t"),
            dynamic=dynamic,
            no_emof=no_emof,
            measured=measured,
            **options,
        )
        return PackagedArchive(written.findings, measured)


def write_archive_from_table(
    *,
    core: Table,
    core_header: list[str],
    extensions: dict[str, Path],
    manifest: Manifest,
    dataset_id: str,
    generated_at: str,
    term_table: dict,
    out_dir: Path,
    mixs_uri_style: MixsUriStyle = "gensc",
    no_dna_extension: bool = False,
    no_emof: bool = False,
    exclusions: Sequence[str] = (),
    units: dict[str, tuple[str, str]] | None = None,
    measured: Collection[str],
    dynamic: DynamicProperties,
) -> WrittenArchive:
    if mixs_uri_style not in MIXS_URI_STYLES:
        raise ArchiveBuildError(
            f"mixs_uri_style must be {' or '.join(map(repr, MIXS_URI_STYLES))}, "
            f"got {mixs_uri_style!r}"
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
    eml_rows = core
    ext_specs = [
        TableSpec(
            key, read_tsv(core.con, path, f"extension_{key}"), tuple(read_header(path, "\t"))
        )
        for key, path in extensions.items()
    ]

    if not no_dna_extension:
        dna_result = dna_derived_data.select_and_build_dna(core, core_header, term_table)
        core_header = dna_result.core_header
        findings.findings.extend(dna_result.findings.findings)
        if dna_result.dna is not None:
            if DNA_KEY in extensions:
                raise ArchiveBuildError(
                    "the DNADerivedData extension is on by default and selected sequence "
                    f"columns, but --extension {DNA_KEY}=... was also given. Pass "
                    "--no-dna-extension to supply your own DNADerivedData table instead"
                )
            ext_specs.append(TableSpec(DNA_KEY, dna_result.dna, tuple(dna_result.dna_header)))

    selected: Collection[str] = ()
    if not no_emof:
        entries = emof.dynamic_entries(core, dynamic)
        selected = entries.measurement_keys(measured)
        emof_rows, emof_findings = emof.build_emof(entries.table, selected, units=units)
        findings.findings.extend(entries.malformed.findings + emof_findings.findings)
        if emof_rows.count():
            if EMOF_KEY in extensions:
                raise ArchiveBuildError(
                    "eMoF is on by default and selected real measurement columns, but "
                    f"--extension {EMOF_KEY}=... was also given. Pass --no-emof to supply your "
                    "own eMoF table instead"
                )
            ext_specs.append(TableSpec(EMOF_KEY, emof_rows, emof.EMOF_HEADER, (ROW, emof.INDEX)))
    check_no_duplicate_row_types(["occurrence", *(s.key for s in ext_specs)])
    core = dynamic.folded(core, removed=selected, as_given=no_emof)
    if DYNAMIC_PROPERTIES in core_header and not core.count(
        f"{column(DYNAMIC_PROPERTIES)} IS NOT NULL"
    ):
        core_header = [name for name in core_header if name != DYNAMIC_PROPERTIES]

    ext_headers: list[tuple[TableSpec, list[str]]] = []
    for spec in ext_specs:
        header = list(spec.header)
        if "dynamicProperties" in header:
            raise ArchiveBuildError(
                f"{spec.key!r} extension has a dynamicProperties column. "
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

    summary = _scan_eml_summary(eml_rows)

    written = {}
    core_spec = TableSpec("occurrence", core, tuple(core_header))
    for spec, header in [(core_spec, list(core_header)), *ext_headers]:
        name = FILENAME_BY_KEY[spec.key]
        written[name] = number_lines(
            spec.table, f"written_{spec.key}", header, order=spec.order, collapse_breaks=True
        )
        write_lines(written[name], out_dir / name, header)

    meta_root = _build_meta_xml(
        core_header, ext_headers, term_table, mixs_uri_style=mixs_uri_style
    )
    (out_dir / "meta.xml").write_bytes(_pretty_xml_bytes(meta_root))
    (out_dir / "eml.xml").write_text(
        render_eml_xml(
            manifest,
            dataset_id=dataset_id,
            generated_at=generated_at,
            event_date_range=summary.event_date_range,
            kingdoms=summary.kingdoms,
            occurrence_statuses=summary.occurrence_statuses,
            detection_limits=summary.detection_limits,
            exclusions=exclusions,
            data_bounding_box=summary.bounding_box,
        ),
        encoding="utf-8",
    )
    if manifest.bounding_box is None and summary.bounding_box is not None:
        box = summary.bounding_box
        findings.add(
            "GEOGRAPHIC_COVERAGE_DERIVED",
            "metadata.bounding_box is not given, so eml.xml's geographic coverage is the "
            f"smallest box around the published coordinates: west {box.west}, south "
            f"{box.south}, east {box.east}, north {box.north}. Give metadata.bounding_box "
            "to state the study area instead",
        )

    members = [FILENAME_BY_KEY["occurrence"], "meta.xml", "eml.xml"]
    members += [FILENAME_BY_KEY[s.key] for s in ext_specs]
    _write_zip(out_dir, members)

    return WrittenArchive(findings, written)
