from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
import io
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import platformdirs

from edna2dwc.common.result import CommandResult
from edna2dwc.terms.formats import FORMAT_BY_TERM, VOCABULARY_BY_TERM

SIMPLE_DWC_URL = "https://raw.githubusercontent.com/tdwg/dwc/master/dist/simple_dwc_vertical.csv"
DWC_VERSIONS_URL = "https://raw.githubusercontent.com/tdwg/dwc/master/vocabulary/term_versions.csv"
DNA_DERIVED_DATA_URL = "https://rs.gbif.org/extension/gbif/1.0/dna_derived_data_2022-02-23.xml"
EMOF_URL = "https://rs.gbif.org/extension/obis/extended_measurement_or_fact.xml"

OBIS_NS = "http://rs.iobis.org/obis/terms/"

REQUIRED = frozenset({"occurrenceID", "scientificName", "basisOfRecord"})
REQUIRED_IF_OCCURRENCE_CORE = frozenset({"scientificNameID", "kingdom", "occurrenceStatus"})
REQUIRED_IF_EVENT_CORE = frozenset({"eventID"})
REQUIRED_IF_EMOF = frozenset({"measurementType", "measurementValue"})
RECOMMENDED = frozenset(
    {
        "geodeticDatum",
        "organismQuantity",
        "organismQuantityType",
        "taxonRank",
        "taxonID",
        "taxonConceptID",
        "phylum",
        "class",
        "order",
        "family",
        "genus",
        "scientificNameAuthorship",
        "taxonomicStatus",
        "identificationRemarks",
        "verbatimIdentification",
        "eventDate",
        "decimalLatitude",
        "decimalLongitude",
        "parentEventID",
        "locationID",
        "locality",
        "waterBody",
        "verbatimLatitude",
        "verbatimLongitude",
        "coordinateUncertaintyInMeters",
        "minimumDepthInMeters",
        "maximumDepthInMeters",
        "sampleSizeValue",
        "sampleSizeUnit",
        "samplingProtocol",
        "recordedBy",
        "institutionCode",
        "datasetID",
        "datasetName",
        "license",
        "associatedSequences",
        "materialSampleID",
        "measurementUnit",
        "DNA_sequence",
        "target_gene",
        "target_subfragment",
        "pcr_primer_name_forward",
        "pcr_primer_name_reverse",
        "pcr_primer_forward",
        "pcr_primer_reverse",
        "seq_meth",
        "nucl_acid_ext",
        "nucl_acid_amp",
        "otu_class_appr",
        "otu_seq_comp_appr",
        "otu_db",
        "env_broad_scale",
        "env_local_scale",
        "env_medium",
    }
)
DEFAULTS = {
    "basisOfRecord": "MaterialSample",
    "occurrenceStatus": "present",
}

_PAIR_SPECS: tuple[tuple[str, str, str, str | None], ...] = (
    ("sampleSizeValue", "sampleSizeUnit", "error", None),
    ("organismQuantity", "organismQuantityType", "error", None),
    ("measurementValue", "measurementUnit", "warning", None),
    ("decimalLatitude", "decimalLongitude", "error", None),
    ("verbatimLatitude", "verbatimLongitude", "error", None),
    ("minimumDepthInMeters", "maximumDepthInMeters", "warning", None),
    ("scientificName", "scientificNameID", "error", None),
    ("annealingTemp", "annealingTempUnit", "error", None),
    ("eventDate", "eventID", "warning", "occurrence_core_only"),
)

_EXPECTS_SPECS: tuple[tuple[str, str, str], ...] = (
    ("decimalLatitude", "geodeticDatum", "warning"),
    ("decimalLatitude", "coordinateUncertaintyInMeters", "warning"),
    ("footprintWKT", "footprintSRS", "warning"),
    ("DNA_sequence", "target_gene", "warning"),
    ("pcr_primer_forward", "pcr_primer_name_forward", "warning"),
)


def expects_for(name: str) -> list[dict] | None:
    matches = [
        {"then": consequent, "severity": severity}
        for antecedent, consequent, severity in _EXPECTS_SPECS
        if antecedent == name
    ]
    return matches or None


def pairs_for(name: str) -> list[dict] | None:
    matches = []
    for first, second, severity, scope in _PAIR_SPECS:
        if name == first:
            partner = second
        elif name == second:
            partner = first
        else:
            continue
        entry = {"with": partner, "severity": severity}
        if scope is not None:
            entry["scope"] = scope
        matches.append(entry)
    return matches or None


PRIORITY_REQUIRED = frozenset(
    {
        "occurrenceID",
        "basisOfRecord",
        "scientificName",
        "scientificNameID",
        "eventDate",
        "decimalLatitude",
        "decimalLongitude",
        "occurrenceStatus",
        "countryCode",
        "kingdom",
        "geodeticDatum",
        "annealingTemp",
    }
)
PRIORITY_STRONGLY_RECOMMENDED = frozenset(
    {
        "minimumDepthInMeters",
        "maximumDepthInMeters",
        "coordinateUncertaintyInMeters",
        "samplingProtocol",
        "taxonRank",
        "organismQuantity",
        "organismQuantityType",
        "datasetName",
        "dataGeneralizations",
        "informationWithheld",
        "institutionCode",
        "footprintWKT",
        "eventID",
        "recordedBy",
        "sampleSizeValue",
        "sampleSizeUnit",
        "materialSampleID",
        "taxonID",
        "DNA_sequence",
        "target_gene",
        "target_subfragment",
        "pcr_primer_forward",
        "pcr_primer_reverse",
        "pcr_primer_name_forward",
        "pcr_primer_name_reverse",
        "pcr_primer_reference",
        "seq_meth",
        "otu_class_appr",
        "otu_seq_comp_appr",
        "otu_db",
        "sop",
        "annealingTempUnit",
        "pcr_cond",
        "probeReporter",
        "probeQuencher",
        "ampliconSize",
        "thresholdQuantificationCycle",
        "baselineValue",
        "pcr_primer_lod",
        "pcr_primer_loq",
    }
)
PRIORITY_RECOMMENDED = frozenset(
    {
        "associatedSequences",
        "identificationRemarks",
        "identificationReferences",
        "phylum",
        "class",
        "order",
        "family",
        "genus",
    }
)

ALL_PRIORITY_TERM_NAMES = PRIORITY_REQUIRED | PRIORITY_STRONGLY_RECOMMENDED | PRIORITY_RECOMMENDED


def priority_tier_for(name: str) -> str | None:
    if name in PRIORITY_REQUIRED:
        return "required"
    if name in PRIORITY_STRONGLY_RECOMMENDED:
        return "strongly_recommended"
    if name in PRIORITY_RECOMMENDED:
        return "recommended"
    return None


ALL_TIERED_NAMES = (
    REQUIRED
    | REQUIRED_IF_OCCURRENCE_CORE
    | REQUIRED_IF_EVENT_CORE
    | REQUIRED_IF_EMOF
    | RECOMMENDED
    | ALL_PRIORITY_TERM_NAMES
)


@dataclass(frozen=True)
class TermSource:
    name: str
    uri: str
    term_class: str


def tier_for(name: str) -> str:
    if name in REQUIRED:
        return "required"
    if name in REQUIRED_IF_OCCURRENCE_CORE:
        return "required_if_occurrence_core"
    if name in REQUIRED_IF_EVENT_CORE:
        return "required_if_event_core"
    if name in REQUIRED_IF_EMOF:
        return "required_if_emof"
    if name in RECOMMENDED:
        return "recommended"
    return "optional"


def _class_from_organized_in(organized_in: str) -> str:
    last_segment = organized_in.rsplit("/", 1)[-1] if organized_in else ""
    return last_segment or "record-level"


def parse_dwc_and_dublin_core(simple_csv_text: str, versions_csv_text: str) -> list[TermSource]:
    names = [line.strip() for line in simple_csv_text.splitlines() if line.strip()]

    newest_recommended_by_name: dict[str, dict] = {}
    reader = csv.DictReader(io.StringIO(versions_csv_text))
    for row in reader:
        if row.get("status") != "recommended":
            continue
        newest_recommended_by_name.setdefault(row["term_localName"], row)

    simple_dwc_names = set(names)
    names.extend(sorted((ALL_TIERED_NAMES & set(newest_recommended_by_name)) - simple_dwc_names))

    sources = []
    for name in names:
        row = newest_recommended_by_name.get(name)
        if row is None:
            continue
        sources.append(
            TermSource(
                name=name,
                uri=row["term_iri"],
                term_class=_class_from_organized_in(row.get("organized_in", "")),
            )
        )
    return sources


def _parse_gbif_extension_properties(xml_text: str) -> list[tuple[str, str, str]]:
    root = ET.fromstring(xml_text)
    out = []
    for prop in root.iter():
        if prop.tag.rsplit("}", 1)[-1] != "property":
            continue
        name = prop.get("name")
        namespace = prop.get("namespace")
        qual_name = prop.get("qualName")
        if name and namespace and qual_name:
            out.append((name, namespace, qual_name))
    return out


def parse_dna_derived_data_extension(xml_text: str) -> list[TermSource]:
    sources = []
    for name, _namespace, qual_name in _parse_gbif_extension_properties(xml_text):
        sources.append(TermSource(name=name, uri=qual_name, term_class="DNADerivedData"))
    return sources


def parse_emof_extension(xml_text: str) -> list[TermSource]:
    sources = []
    for name, namespace, qual_name in _parse_gbif_extension_properties(xml_text):
        if namespace == OBIS_NS:
            sources.append(TermSource(name=name, uri=qual_name, term_class="MeasurementOrFact"))
    return sources


CACHE_FILENAMES = {
    "simple_csv": "simple_dwc_vertical.csv",
    "versions_csv": "term_versions.csv",
    "dna_derived_xml": "dna_derived_data.xml",
    "emof_xml": "extended_measurement_or_fact.xml",
}


def fetch_raw(client: httpx.Client) -> dict[str, str]:
    return {
        "simple_csv": client.get(SIMPLE_DWC_URL).raise_for_status().text,
        "versions_csv": client.get(DWC_VERSIONS_URL).raise_for_status().text,
        "dna_derived_xml": client.get(DNA_DERIVED_DATA_URL).raise_for_status().text,
        "emof_xml": client.get(EMOF_URL).raise_for_status().text,
    }


def read_cache(cache_dir) -> dict[str, str]:
    raw = {}
    for key, filename in CACHE_FILENAMES.items():
        path = cache_dir / filename
        if not path.exists():
            raise FileNotFoundError(
                f"--offline requested but {path} is missing; run without --offline once first"
            )
        raw[key] = path.read_text(encoding="utf-8")
    return raw


def write_cache(cache_dir, raw: dict[str, str]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for key, filename in CACHE_FILENAMES.items():
        (cache_dir / filename).write_text(raw[key], encoding="utf-8")


def parse_raw(raw: dict[str, str]) -> list[TermSource]:
    return [
        *parse_dwc_and_dublin_core(raw["simple_csv"], raw["versions_csv"]),
        *parse_dna_derived_data_extension(raw["dna_derived_xml"]),
        *parse_emof_extension(raw["emof_xml"]),
    ]


def build_term_table(sources: list[TermSource]) -> dict:
    terms: dict[str, dict] = {}
    for source in sources:
        if source.name in terms:
            continue
        entry: dict = {
            "uri": source.uri,
            "class": source.term_class,
            "tier": tier_for(source.name),
        }
        priority_tier = priority_tier_for(source.name)
        if priority_tier is not None:
            entry["priority_tier"] = priority_tier
        if source.name in DEFAULTS:
            entry["default"] = DEFAULTS[source.name]
        if source.name in FORMAT_BY_TERM:
            entry["format"] = FORMAT_BY_TERM[source.name]
        if source.name in VOCABULARY_BY_TERM:
            entry["vocabulary"] = sorted(VOCABULARY_BY_TERM[source.name])
        pairs = pairs_for(source.name)
        if pairs is not None:
            entry["pairs"] = pairs
        expects = expects_for(source.name)
        if expects is not None:
            entry["expects"] = expects
        terms[source.name] = entry

    missing = sorted(ALL_TIERED_NAMES - set(terms))
    if missing:
        raise ValueError(
            f"terms sync failed closed: {len(missing)} tiered term(s) not found in any fetched "
            f"source: {', '.join(missing)}"
        )

    return terms


def sync(cache_dir, *, offline: bool = False, client: httpx.Client | None = None) -> dict:
    if offline:
        raw = read_cache(cache_dir)
    else:
        if client is not None:
            raw = fetch_raw(client)
        else:
            with httpx.Client(timeout=30) as owned_client:
                raw = fetch_raw(owned_client)
        write_cache(cache_dir, raw)

    terms = build_term_table(parse_raw(raw))
    accessed = datetime.now(UTC).strftime("%Y-%m-%d")
    counts_by_class: dict[str, int] = {}
    for entry in terms.values():
        counts_by_class[entry["class"]] = counts_by_class.get(entry["class"], 0) + 1
    return {
        **terms,
        "_notes": {
            "accessed": accessed,
            "sources": [SIMPLE_DWC_URL, DWC_VERSIONS_URL, DNA_DERIVED_DATA_URL, EMOF_URL],
            "term_count": len(terms),
            "term_count_by_class": counts_by_class,
        },
    }


def cache_dir() -> Path:
    return Path(platformdirs.user_cache_dir("edna2dwc")) / "terms_sync"


def step(*, offline: bool = False, output: Path) -> CommandResult:
    table = sync(cache_dir(), offline=offline)
    output.write_text(json.dumps(table, indent=2, sort_keys=True), encoding="utf-8")
    return CommandResult(
        command="terms sync",
        outputs={"term_table": str(output)},
        text=f"Wrote {table['_notes']['term_count']} terms to {output}",
    )
