from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from edna2dwc.common import pages
from edna2dwc.conversion import stages
from edna2dwc.inputs.inspect import InspectReport
from edna2dwc.terms.map_terms import propose_mapping

PAGE_NAME = Path("INSPECTION.md")
HEADER_SCAN_LIMIT = 10

READ_WITH = {
    "xlsx": "pandas.read_excel",
    "delimited": "pandas.read_csv",
    "qza": "zipfile, then h5py for a feature table",
    "biom-json-v1": "json",
    "biom-hdf5": "h5py",
    "rds": "Rscript, exporting each table to CSV",
    "fasta": "assemble --sequences, joined on featureID",
    "zip": "zipfile, then inspect its files",
}

FEATURE_TABLE_FORMATS = frozenset({"biom-json-v1", "biom-hdf5", "rds"})

TAXONOMY_HEADERS = frozenset(
    {
        "taxon",
        "taxonomy",
        "lineage",
        "classification",
        "kingdom",
        "phylum",
        "class",
        "order",
        "family",
        "genus",
    }
)

TIER_LABELS = {"required": "required", "strongly_recommended": "strongly recommended"}

DERIVED = {
    "occurrenceID": "from the dataset id, the sample and the feature",
    "scientificName": "from the taxonomy resolved against WoRMS and GBIF",
    "scientificNameID": "from the taxonomy resolved against WoRMS and GBIF",
    "kingdom": "from the taxonomy resolved against WoRMS and GBIF",
    "taxonRank": "from the taxonomy resolved against WoRMS and GBIF",
    "taxonID": "from the MD5 of each feature's sequence, blank without one",
    "occurrenceStatus": "present on every detection",
    "organismQuantity": "from the read counts",
    "organismQuantityType": "from the read counts",
    "sampleSizeValue": "from the read counts",
    "sampleSizeUnit": "from the read counts",
    "countryCode": "from the coordinates",
    "basisOfRecord": "MaterialSample, true of every eDNA record",
}
NEEDS_TAXONOMY = frozenset({"scientificName", "scientificNameID", "kingdom", "taxonRank"})
NEEDS_COORDINATES = frozenset({"countryCode"})
COORDINATE_TERMS = ("decimalLatitude", "decimalLongitude")


@dataclass(frozen=True)
class FileEntry:
    path: str
    format: str
    role: str
    read_with: str


@dataclass(frozen=True)
class FoundColumn:
    term: str
    file: str
    table: str
    column: str


@dataclass(frozen=True)
class TermStatus:
    term: str
    tier: str
    status: str
    source: str


@dataclass
class Readiness:
    files: list[FileEntry]
    feature_tables: list[str]
    taxonomy_sources: list[str]
    found: list[FoundColumn]
    terms: list[TermStatus]
    decisions: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[TermStatus]:
        return [t for t in self.terms if t.status == "missing"]

    def to_dict(self) -> dict:
        return {
            "files": [asdict(f) for f in self.files],
            "feature_tables": self.feature_tables,
            "taxonomy_sources": self.taxonomy_sources,
            "found": [asdict(c) for c in self.found],
            "terms": [asdict(t) for t in self.terms],
            "decisions": self.decisions,
        }


def _file_entry(report: InspectReport) -> FileEntry:
    if report.format == "document":
        return FileEntry(
            report.path, report.format, "documentation", "edna2dwc text, for dataset metadata"
        )
    if report.format.startswith("unrecognized"):
        return FileEntry(
            report.path, report.format, "unrecognized", "the format's own tools, once identified"
        )
    return FileEntry(report.path, report.format, "data", READ_WITH.get(report.format, ""))


def _looks_like_header(row: tuple) -> bool:
    non_blank = [c for c in row if c is not None and str(c).strip() != ""]
    return len(non_blank) >= 2 and not any(isinstance(c, (int, float)) for c in non_blank)


def _looks_like_data(row: tuple) -> bool:
    non_blank = [c for c in row if c is not None and str(c).strip() != ""]
    return any(isinstance(c, (int, float)) for c in non_blank)


def detect_header_row(rows: list[tuple]) -> int:
    limit = min(HEADER_SCAN_LIMIT, len(rows) - 1) if len(rows) > 1 else 0
    for i in range(limit):
        if _looks_like_header(rows[i]) and _looks_like_data(rows[i + 1]):
            return i + 1
    return 1


def _headers(report: InspectReport) -> list[tuple[str, list[str], list[list[str]]]]:
    if report.format == "delimited":
        return [("", report.summary.get("header", []), report.summary.get("preview_rows", []))]
    if report.format == "xlsx":
        tables = []
        for sheet in report.summary.get("sheets", []):
            preview = [row for row in sheet.values() if isinstance(row, list)]
            rows = preview[0] if preview else []
            if not rows:
                continue
            header_row = detect_header_row([tuple(r) for r in rows])
            tables.append((sheet["name"], rows[header_row - 1], rows[header_row:]))
        return tables
    if report.format == "qza":
        return [
            (name.rsplit("/", 1)[-1], text.splitlines()[0].split("\t"), [])
            for name, text in report.summary.get("data_file_previews", {}).items()
            if text.strip()
        ]
    return []


def _is_number(cell: str) -> bool:
    try:
        float(cell)
    except ValueError:
        return False
    return True


def _looks_like_count_matrix(header: list[str], rows: list[list[str]]) -> bool:
    if len(header) < 3 or not rows:
        return False
    numeric = sum(_is_number(cell) for row in rows for cell in row[1:] if cell != "")
    total = sum(1 for row in rows for cell in row[1:] if cell != "")
    return total > 0 and numeric == total


def _is_feature_table(report: InspectReport) -> bool:
    if report.format in FEATURE_TABLE_FORMATS:
        return True
    if report.format == "qza":
        return "FeatureTable" in (report.summary.get("metadata_yaml_preview") or "")
    return False


def _has_taxonomy(report: InspectReport) -> bool:
    if report.format == "biom-json-v1":
        return any(
            (row.get("metadata") or {}).get("taxonomy")
            for row in report.summary.get("first_3_rows", [])
        )
    if report.format == "biom-hdf5":
        return any(row.get("taxonomy") for row in report.summary.get("first_3_rows", []))
    if report.format == "qza":
        return "Taxonomy" in (report.summary.get("metadata_yaml_preview") or "")
    return False


def assess(reports: list[InspectReport], term_table: dict) -> Readiness:
    files = [_file_entry(r) for r in reports]
    feature_tables = [r.path for r in reports if _is_feature_table(r)]
    taxonomy_sources = [r.path for r in reports if _has_taxonomy(r)]
    found: list[FoundColumn] = []
    for report in reports:
        for table, header, rows in _headers(report):
            where = f"{report.path}" + (f" / {table}" if table else "")
            if _looks_like_count_matrix(header, rows):
                feature_tables.append(where)
            if any(h.strip().casefold() in TAXONOMY_HEADERS for h in header):
                taxonomy_sources.append(where)
            proposals, _ = propose_mapping(header, term_table)
            found += [
                FoundColumn(p.target, report.path, table, p.source_column)
                for p in proposals
                if p.target and p.target != "dynamicProperties"
            ]

    supplied = {c.term for c in found}
    has_coordinates = all(term in supplied for term in COORDINATE_TERMS)
    terms = []
    for name, entry in sorted(term_table.items()):
        tier = entry.get("priority_tier")
        if tier not in TIER_LABELS:
            continue
        if name in supplied:
            source = next(c for c in found if c.term == name)
            where = source.file + (f" / {source.table}" if source.table else "")
            terms.append(TermStatus(name, TIER_LABELS[tier], "found", f"{where}: {source.column}"))
        elif name in DERIVED and (
            (name not in NEEDS_TAXONOMY or taxonomy_sources)
            and (name not in NEEDS_COORDINATES or has_coordinates)
        ):
            terms.append(TermStatus(name, TIER_LABELS[tier], "derived", DERIVED[name]))
        else:
            terms.append(TermStatus(name, TIER_LABELS[tier], "missing", ""))
    terms.sort(key=lambda t: (t.tier != "required", t.term))

    documentation = [f.path for f in files if f.role == "documentation"]
    decisions = [
        (
            "**What each marker amplifies**, once the markers are known. Answer from primer "
            "sequences or the methods, never from the marker's name: 16S names both a bacterial "
            "and a vertebrate target."
        ),
        "**Dataset metadata** that no table contains: title, creators, abstract, license, contacts."
        + (
            " Look in " + ", ".join(f"`{d}`" for d in documentation) + " first."
            if documentation
            else " No documentation file was found beside the data, so these will be asked for."
        ),
    ]
    if any(f.role == "unrecognized" for f in files) or any(
        len(r.summary.get("sheets", [])) > 1 for r in reports
    ):
        decisions.append(
            "**Which reading of a layout is right**, if a sheet or a file can be read two ways."
        )
    return Readiness(files, feature_tables, taxonomy_sources, found, terms, decisions)


def render_markdown(readiness: Readiness, *, inputs: list[str]) -> str:
    roles = {
        role: sum(1 for f in readiness.files if f.role == role)
        for role in ("data", "documentation", "unrecognized")
    }
    lines = [f"# Inspection of {', '.join(inputs)}", ""]
    lines.append(
        f"- {len(readiness.files)} file(s): {roles['data']} data, {roles['documentation']} documentation, "
        f"{roles['unrecognized']} in a format inspect doesn't know."
    )
    lines.append(
        "- Feature table: "
        + (
            ", ".join(f"`{p}`" for p in readiness.feature_tables)
            or "none recognized. Every conversion needs one: a sample by feature count table."
        )
    )
    lines.append(
        "- Taxonomy: "
        + (
            ", ".join(f"`{p}`" for p in readiness.taxonomy_sources)
            or "no taxonomy column or artifact found, so no name can be resolved."
        )
    )
    supplied = {c.term for c in readiness.found}
    lines.append(
        "- Coordinates: "
        + (
            "found."
            if all(t in supplied for t in COORDINATE_TERMS)
            else "not found in any column. `countryCode` cannot be derived without them."
        )
    )
    lines.append("- Dates: " + ("found." if "eventDate" in supplied else "no date column found."))
    lines.append("")

    lines += ["## How this conversion goes", "", *stages.overview(), ""]
    lines += ["## Questions you will be asked", ""]
    lines += [f"- {d}" for d in readiness.decisions]
    lines.append("")

    lines += ["## Files", ""]
    lines += pages.table(
        ["File", "Format", "What it is", "Read with"],
        [[f"`{f.path}`", f.format, f.role, f.read_with] for f in readiness.files],
    )
    lines.append("")

    lines += ["## Darwin Core terms the files supply", ""]
    if readiness.found:
        lines += pages.table(
            ["Term", "File", "Sheet or table", "Column"],
            [[f"`{c.term}`", f"`{c.file}`", c.table, f"`{c.column}`"] for c in readiness.found],
        )
        lines += [
            "",
            "Matched on column name alone. `build` proposes the full mapping for review in proposed/term_mapping.tsv once the table is read.",
        ]
    else:
        lines.append("No column name matched a Darwin Core term or a known alias.")
    lines.append("")

    derived = [t for t in readiness.terms if t.status == "derived"]
    lines += ["## Terms the tool derives", ""]
    lines += pages.table(
        ["Term", "Tier", "How"], [[f"`{t.term}`", t.tier, t.source] for t in derived]
    )
    lines.append("")

    lines += ["## Terms nothing supplies", ""]
    if readiness.missing:
        lines.append(
            "GBIF and OBIS expect these and no column, artifact or derivation provides them. Each is "
            "left blank unless a documentation file or the researcher supplies it as a constant with its "
            "provenance. Never invent one. A term that does not apply to this study design, such as "
            "the qPCR block on a metabarcoding dataset, is recorded as not applicable by `build` "
            "and stops counting as missing; answers.yaml's term_states: records any other."
        )
        lines.append("")
        lines += pages.table(
            ["Term", "Tier"], [[f"`{t.term}`", t.tier] for t in readiness.missing]
        )
    else:
        lines.append("Nothing. Every expected term is supplied or derived.")
    lines.append("")

    return "\n".join(lines)


def write(readiness: Readiness, *, inputs: list[str], directory: Path) -> tuple[Path, Path]:
    return pages.write_page(directory / PAGE_NAME, render_markdown(readiness, inputs=inputs))
