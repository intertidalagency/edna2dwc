from __future__ import annotations

from xml.etree import ElementTree as ET


DATASET_TYPE_KEYWORDS = ("Occurrence", "DNA derived data")
KEYWORD_THESAURUS = "GBIF Dataset Type Vocabulary"

GBIF_HIERARCHY_LEVEL = "dataset"

DEFAULT_LANGUAGE = "eng"
DEFAULT_MAINTENANCE_DESCRIPTION = "Update frequency not specified."

_EML_NS = "eml://ecoinformatics.org/eml-2.1.1"
_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
_DC_NS = "http://purl.org/dc/terms/"
_SCHEMA_LOCATION = (
    "eml://ecoinformatics.org/eml-2.1.1 https://rs.gbif.org/schema/eml-gbif-profile/1.2/eml.xsd"
)


class EmlRenderError(ValueError):


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


def _para(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = _sub(parent, tag)
    _sub(el, "para", text)
    return el






def render_eml_xml(
    manifest: Manifest,
    *,
    dataset_id: str,
    generated_at: str,
    event_date_range: tuple[str, str] | None = None,
    kingdoms: list[str] | None = None,
) -> str:

    root = ET.Element(
        "eml:eml",
        {
            "xmlns:eml": _EML_NS,
            "xmlns:dc": _DC_NS,
            "xmlns:xsi": _XSI_NS,
            "xsi:schemaLocation": _SCHEMA_LOCATION,
            "system": "http://gbif.org",
            "scope": "system",
            "xml:lang": "eng",
        },
    )
    dataset = _sub(root, "dataset")


    _sub(dataset, "language", DEFAULT_LANGUAGE)

    keyword_set = _sub(dataset, "keywordSet")
    for keyword in DATASET_TYPE_KEYWORDS:
        _sub(keyword_set, "keyword", keyword)
    _sub(keyword_set, "keywordThesaurus", KEYWORD_THESAURUS)


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


        methods = _sub(dataset, "methods")

    additional_metadata = _sub(root, "additionalMetadata")
    gbif_block = _sub(_sub(additional_metadata, "metadata"), "gbif")
    _sub(gbif_block, "dateStamp", generated_at)
    _sub(gbif_block, "hierarchyLevel", GBIF_HIERARCHY_LEVEL)

    xml_bytes = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}\n'
