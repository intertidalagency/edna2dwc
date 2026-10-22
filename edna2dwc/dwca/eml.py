from __future__ import annotations

from collections.abc import Collection
from xml.etree import ElementTree as ET

from edna2dwc.dwca.manifest import (
    GBIF_LICENSES,
    REQUIRED_METADATA,
    BoundingBox,
    Manifest,
    Person,
    Project,
    gbif_license,
)

DATASET_TYPE_KEYWORDS = ("Occurrence", "DNA derived data")
KEYWORD_THESAURUS = "GBIF Dataset Type Vocabulary"

GBIF_HIERARCHY_LEVEL = "dataset"

DEFAULT_LANGUAGE = "eng"
GBIF_PROFILE_SPELLING_OF_UNKNOWN = "unkown"
DEFAULT_MAINTENANCE_DESCRIPTION = "Update frequency not specified."
ORCID_DIRECTORY = "https://orcid.org/"
DERIVED_BOX_DESCRIPTION = (
    "The bounding box is the smallest that contains every coordinate in this archive."
)

_EML_NS = "eml://ecoinformatics.org/eml-2.1.1"
_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
_DC_NS = "http://purl.org/dc/terms/"
_SCHEMA_LOCATION = (
    "eml://ecoinformatics.org/eml-2.1.1 https://rs.gbif.org/schema/eml-gbif-profile/1.2/eml.xsd"
)


class EmlRenderError(ValueError):
    pass


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


def _para(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = _sub(parent, tag)
    _sub(el, "para", text)
    return el


def _license(dataset: ET.Element, value: str) -> None:
    license_id = gbif_license(value)
    if license_id is None:
        raise EmlRenderError(
            f"license {value!r} is not one GBIF accepts: {', '.join(GBIF_LICENSES)}"
        )
    title, url = GBIF_LICENSES[license_id]
    para = _sub(_sub(dataset, "intellectualRights"), "para", "This work is licensed under a ")
    link = _sub(para, "ulink")
    link.set("url", url)
    _sub(link, "citetitle", f"{title} License")
    link.tail = "."


def _responsible_party(parent: ET.Element, tag: str, person: Person) -> ET.Element:
    party = _sub(parent, tag)
    if person.surname:
        individual = _sub(party, "individualName")
        if person.given:
            _sub(individual, "givenName", person.given)
        _sub(individual, "surName", person.surname)
    if person.organization:
        _sub(party, "organizationName", person.organization)
    if person.email:
        _sub(party, "electronicMailAddress", person.email)
    if person.orcid:
        _sub(party, "userId", person.orcid).set("directory", ORCID_DIRECTORY)
    return party


def _project(dataset: ET.Element, project: Project) -> None:
    element = _sub(dataset, "project")
    _sub(element, "title", project.title)
    for member in project.personnel:
        _sub(_responsible_party(element, "personnel", member.person), "role", member.role)
    if project.funding:
        _para(element, "funding", project.funding)


def _exclusions_step(exclusions: Collection[str]) -> str:
    if not exclusions:
        return ""
    return "Excluded before publishing: " + "; ".join(exclusions) + "."


def _status_convention(
    occurrence_statuses: Collection[str], detection_limits: Collection[str]
) -> str:
    if "absent" in occurrence_statuses:
        published = (
            "Zero-count records are published as absences (occurrenceStatus=absent) rather "
            "than dropped."
        )
        if not detection_limits:
            return (
                f"{published} An absence states only that no reads were counted: no "
                "pcr_primer_lod is recorded in this archive."
            )
        return (
            f"{published} An absence means the target was not detected above the assay's "
            f"limit of detection, recorded as pcr_primer_lod: {'; '.join(detection_limits)}."
        )
    if "present" in occurrence_statuses:
        return "Presence-only: zero-count records are not published as absences."
    return ""


def _geographic_coverage(
    manifest: Manifest, data_bounding_box: BoundingBox | None
) -> ET.Element | None:
    description = manifest.values.get("geographic_description", "")
    box = manifest.bounding_box
    if box is None and data_bounding_box is not None:
        box = data_bounding_box
        description = " ".join(part for part in (description, DERIVED_BOX_DESCRIPTION) if part)
    if not description or box is None:
        return None
    geo = ET.Element("geographicCoverage")
    _sub(geo, "geographicDescription", description)
    bounds = _sub(geo, "boundingCoordinates")
    _sub(bounds, "westBoundingCoordinate", str(box.west))
    _sub(bounds, "eastBoundingCoordinate", str(box.east))
    _sub(bounds, "northBoundingCoordinate", str(box.north))
    _sub(bounds, "southBoundingCoordinate", str(box.south))
    return geo


PROFILE_REQUIRED_ELEMENTS = {
    "title": "title",
    "creators": "creator",
    "pub_date": "pubDate",
    "abstract": "abstract",
    "contacts": "contact",
}


def missing_profile_elements(manifest: Manifest) -> list[str]:
    return sorted(
        element
        for field, element in PROFILE_REQUIRED_ELEMENTS.items()
        if not manifest.is_set(field)
    )


def render_eml_xml(
    manifest: Manifest,
    *,
    dataset_id: str,
    generated_at: str,
    event_date_range: tuple[str, str] | None = None,
    kingdoms: list[str] | None = None,
    occurrence_statuses: Collection[str] = (),
    detection_limits: Collection[str] = (),
    exclusions: Collection[str] = (),
    data_bounding_box: BoundingBox | None = None,
) -> str:
    for field in REQUIRED_METADATA:
        if manifest.is_open(field):
            raise EmlRenderError(f"manifest is missing required field {field!r} for eml.xml")

    root = ET.Element(
        "eml:eml",
        {
            "xmlns:eml": _EML_NS,
            "xmlns:dc": _DC_NS,
            "xmlns:xsi": _XSI_NS,
            "xsi:schemaLocation": _SCHEMA_LOCATION,
            "packageId": f"{dataset_id}/v{manifest.version}",
            "system": "http://gbif.org",
            "scope": "system",
            "xml:lang": "eng",
        },
    )
    dataset = _sub(root, "dataset")
    if manifest.is_set("title"):
        _sub(dataset, "title", manifest.values["title"]).set("xml:lang", "eng")

    for creator in manifest.people.get("creators", []):
        _responsible_party(dataset, "creator", creator)

    if manifest.is_set("pub_date"):
        _sub(dataset, "pubDate", manifest.values["pub_date"])
    _sub(dataset, "language", DEFAULT_LANGUAGE)
    if manifest.is_set("abstract"):
        _para(dataset, "abstract", manifest.values["abstract"])

    keyword_set = _sub(dataset, "keywordSet")
    for keyword in DATASET_TYPE_KEYWORDS:
        _sub(keyword_set, "keyword", keyword)
    _sub(keyword_set, "keywordThesaurus", KEYWORD_THESAURUS)

    if manifest.is_set("license"):
        _license(dataset, manifest.values["license"])

    geographic = _geographic_coverage(manifest, data_bounding_box)
    coverage_children = [] if geographic is None else [geographic]
    if event_date_range is not None:
        begin, end = event_date_range
        temporal = ET.Element("temporalCoverage")
        range_of_dates = _sub(temporal, "rangeOfDates")
        _sub(_sub(range_of_dates, "beginDate"), "calendarDate", begin)
        _sub(_sub(range_of_dates, "endDate"), "calendarDate", end)
        coverage_children.append(temporal)
    if kingdoms:
        taxonomic = ET.Element("taxonomicCoverage")
        for kingdom in kingdoms:
            classification = _sub(taxonomic, "taxonomicClassification")
            _sub(classification, "taxonRankName", "Kingdom")
            _sub(classification, "taxonRankValue", kingdom)
        coverage_children.append(taxonomic)
    if coverage_children:
        coverage = _sub(dataset, "coverage")
        coverage.extend(coverage_children)

    maintenance = _sub(dataset, "maintenance")
    _para(maintenance, "description", DEFAULT_MAINTENANCE_DESCRIPTION)
    _sub(maintenance, "maintenanceUpdateFrequency", GBIF_PROFILE_SPELLING_OF_UNKNOWN)

    for contact in manifest.people.get("contacts", []):
        _responsible_party(dataset, "contact", contact)

    method_steps = [
        text
        for text in (
            manifest.values.get("methods_description"),
            _status_convention(occurrence_statuses, detection_limits),
            _exclusions_step(exclusions),
        )
        if text
    ]
    if method_steps:
        methods = _sub(dataset, "methods")
        for text in method_steps:
            _para(_sub(methods, "methodStep"), "description", text)
    if manifest.project is not None:
        _project(dataset, manifest.project)

    additional_metadata = _sub(root, "additionalMetadata")
    gbif_block = _sub(_sub(additional_metadata, "metadata"), "gbif")
    _sub(gbif_block, "dateStamp", generated_at)
    _sub(gbif_block, "hierarchyLevel", GBIF_HIERARCHY_LEVEL)

    xml_bytes = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}\n'
