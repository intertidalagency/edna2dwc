from xml.etree import ElementTree as ET

import pytest

from edna2dwc.dwca import eml
from edna2dwc.dwca.manifest import BoundingBox, Manifest, Person, Project, ProjectMember
from tests import elements, manifests
from tests.paths import PACKAGE_DIR

DATA_BOX = BoundingBox(west=-122.46, south=47.56, east=-122.44, north=47.76)
PRESENCE_ONLY = "Presence-only: zero-count records are not published as absences."
ABSENCES = (
    "Zero-count records are published as absences (occurrenceStatus=absent) rather than dropped."
)


def _full_manifest() -> Manifest:
    m = Manifest()
    m.set("title", "Monterey Bay eDNA time series", provenance="title")
    m.set_people(
        "creators",
        [
            Person(
                given="Jane",
                surname="Smith",
                organization="MBARI",
                email="jsmith@mbari.org",
                orcid="0000-0002-1825-0097",
            ),
            Person(given="A.", surname="Doe"),
            Person(organization="Monterey Bay Aquarium Research Institute"),
        ],
        provenance="creators",
    )
    m.set("abstract", "An 18S metabarcoding survey.", provenance="abstract")
    m.set("license", "https://creativecommons.org/publicdomain/zero/1.0/", provenance="license")
    m.set_people(
        "contacts",
        [Person(given="Jane", surname="Smith"), Person(surname="Doe", email="doe@mbari.org")],
        provenance="contacts",
    )
    m.set("pub_date", "2024-01-15", provenance="pub_date")
    m.set(
        "geographic_description",
        "Monterey Bay, California",
        provenance="geographic_description",
    )
    m.set_bounding_box(
        BoundingBox(west=-122.1, south=36.5, east=-121.8, north=36.8),
        provenance="bounding_box",
    )
    return m


def _without_bounding_box() -> Manifest:
    m = _full_manifest()
    m.bounding_box = None
    return m


def _with_methods(text: str = "Real methods text.") -> Manifest:
    m = _full_manifest()
    m.set("methods_description", text, provenance="methods_description")
    return m


def _with_project() -> Manifest:
    m = _full_manifest()
    lead = ProjectMember(Person(given="Jane", surname="Smith"), "principalInvestigator")
    m.set_project(Project("Monterey Bay eDNA", (lead,), "NSF award 1234567"), provenance="PI")
    return m


def _render(manifest: Manifest | None = None, **options) -> ET.Element:
    return ET.fromstring(_render_text(manifest, **options))


def _render_text(manifest: Manifest | None = None, **options) -> str:
    return eml.render_eml_xml(
        _full_manifest() if manifest is None else manifest,
        dataset_id=options.pop("dataset_id", "ds-1"),
        generated_at=options.pop("generated_at", "2024-06-01T00:00:00Z"),
        **options,
    )


def _method_paras(root: ET.Element) -> list[str]:
    return [p.text or "" for p in root.findall("dataset/methods/methodStep/description/para")]


def _bounding_coordinates(root: ET.Element) -> dict[str, str | None]:
    return {c.tag: c.text for c in elements.child(root, ".//boundingCoordinates")}


def _geographic_description(root: ET.Element) -> str:
    return elements.child_text(root, ".//geographicDescription") or ""


@pytest.mark.parametrize(
    ("version", "package_id"), [(None, "urn:uuid:abc-123/v1"), (3, "urn:uuid:abc-123/v3")]
)
def test_the_package_id_is_the_dataset_id_and_the_metadata_version(version, package_id):
    manifest = _full_manifest()
    if version is not None:
        manifest.version = version
    assert _render(manifest, dataset_id="urn:uuid:abc-123").get("packageId") == package_id


def test_render_eml_xml_element_order_matches_the_schema_sequence():
    assert [c.tag for c in elements.child(_render(), "dataset")] == [
        "title",
        "creator",
        "creator",
        "creator",
        "pubDate",
        "language",
        "abstract",
        "keywordSet",
        "intellectualRights",
        "coverage",
        "maintenance",
        "contact",
        "contact",
    ]


def test_render_eml_xml_maintenance_is_a_described_para_then_a_frequency():
    maintenance = elements.child(_render(), "dataset/maintenance")
    assert [c.tag for c in maintenance] == ["description", "maintenanceUpdateFrequency"]
    description = elements.child(maintenance, "description")
    assert [c.tag for c in description] == ["para"]
    assert description.text is None or not description.text.strip()


def test_render_eml_xml_writes_each_part_of_a_person_to_its_own_element():
    creator = elements.child(_render(), "dataset/creator")
    assert elements.child_text(creator, "individualName/givenName") == "Jane"
    assert elements.child_text(creator, "individualName/surName") == "Smith"
    assert elements.child_text(creator, "organizationName") == "MBARI"
    assert elements.child_text(creator, "electronicMailAddress") == "jsmith@mbari.org"
    user_id = elements.child(creator, "userId")
    assert user_id.text == "0000-0002-1825-0097"
    assert user_id.get("directory") == "https://orcid.org/"


def test_render_eml_xml_writes_an_organization_without_an_individual_name():
    organization = _render().findall("dataset/creator")[2]
    assert [c.tag for c in organization] == ["organizationName"]


def test_render_eml_xml_writes_one_contact_element_per_contact():
    contacts = _render().findall("dataset/contact")
    assert [elements.child_text(c, "individualName/surName") for c in contacts] == [
        "Smith",
        "Doe",
    ]
    assert elements.child_text(contacts[1], "electronicMailAddress") == "doe@mbari.org"


def test_render_eml_xml_writes_the_project_lead_and_funding():
    root = _render(_with_project())
    assert root.findtext(".//project/personnel/role") == "principalInvestigator"
    assert root.findtext(".//project/funding/para") == "NSF award 1234567"


@pytest.mark.parametrize(
    "missing_field", ["title", "creators", "abstract", "license", "contacts", "pub_date"]
)
def test_render_eml_xml_raises_on_a_missing_required_field(missing_field):
    m = _full_manifest()
    m.values.pop(missing_field, None)
    m.people.pop(missing_field, None)
    m.provenance.pop(missing_field, None)
    with pytest.raises(eml.EmlRenderError, match=missing_field):
        _render(m)


def test_render_eml_xml_omits_temporal_and_taxonomic_coverage_and_methods_with_no_real_data():
    root = _render()
    assert root.find(".//temporalCoverage") is None
    assert root.find(".//taxonomicCoverage") is None
    assert root.find("dataset/methods") is None


def test_render_eml_xml_coverage_is_geographic_then_temporal_then_taxonomic():
    root = _render(
        event_date_range=("2021-06-01", "2021-06-05"), kingdoms=["Animalia", "Chromista"]
    )
    coverage = elements.child(root, "dataset/coverage")
    assert [c.tag for c in coverage] == [
        "geographicCoverage",
        "temporalCoverage",
        "taxonomicCoverage",
    ]
    assert _bounding_coordinates(root) == {
        "westBoundingCoordinate": "-122.1",
        "eastBoundingCoordinate": "-121.8",
        "northBoundingCoordinate": "36.8",
        "southBoundingCoordinate": "36.5",
    }
    range_of_dates = elements.child(coverage, "temporalCoverage/rangeOfDates")
    assert elements.child_text(range_of_dates, "beginDate/calendarDate") == "2021-06-01"
    assert elements.child_text(range_of_dates, "endDate/calendarDate") == "2021-06-05"
    classifications = coverage.findall("taxonomicCoverage/taxonomicClassification")
    assert [elements.child_text(c, "taxonRankValue") for c in classifications] == [
        "Animalia",
        "Chromista",
    ]
    assert elements.child_text(classifications[0], "taxonRankName") == "Kingdom"


def test_render_eml_xml_methods_is_the_last_dataset_child_and_holds_the_description():
    root = _render(_with_methods("DNA extracted with a Qiagen kit and sequenced on a MiSeq."))
    assert [c.tag for c in elements.child(root, "dataset")][-1] == "methods"
    assert _method_paras(root) == ["DNA extracted with a Qiagen kit and sequenced on a MiSeq."]


def test_geographic_coverage_falls_back_to_the_box_of_the_published_coordinates():
    root = _render(manifests.required_manifest(), data_bounding_box=DATA_BOX)
    assert _bounding_coordinates(root) == {
        "westBoundingCoordinate": "-122.46",
        "eastBoundingCoordinate": "-122.44",
        "northBoundingCoordinate": "47.76",
        "southBoundingCoordinate": "47.56",
    }
    assert eml.DERIVED_BOX_DESCRIPTION in _geographic_description(root)


def test_a_derived_box_keeps_the_given_geographic_description():
    description = _geographic_description(
        _render(_without_bounding_box(), data_bounding_box=DATA_BOX)
    )
    assert description.startswith("Monterey Bay, California")
    assert eml.DERIVED_BOX_DESCRIPTION in description


def test_a_given_bounding_box_wins_over_the_box_of_the_data():
    root = _render(data_bounding_box=DATA_BOX)
    assert _bounding_coordinates(root)["westBoundingCoordinate"] == "-122.1"
    assert eml.DERIVED_BOX_DESCRIPTION not in _geographic_description(root)


def test_render_eml_xml_omits_geographic_coverage_entirely_without_a_bounding_box():
    root = _render(_without_bounding_box())
    assert root.find(".//geographicCoverage") is None


def test_render_eml_xml_omits_geographic_coverage_without_a_description():
    m = _full_manifest()
    m.values.pop("geographic_description")
    assert _render(m).find(".//geographicCoverage") is None


def test_render_eml_xml_omits_coverage_entirely_with_no_real_data_at_all():
    m = _without_bounding_box()
    m.values.pop("geographic_description")
    assert _render(m).find(".//coverage") is None


@pytest.mark.parametrize(
    ("manifest", "options"),
    [
        (manifests.required_manifest, {}),
        (manifests.required_manifest, {"data_bounding_box": DATA_BOX}),
        (_without_bounding_box, {}),
        (_with_project, {}),
        (
            _with_methods,
            {
                "event_date_range": ("2021-06-01", "2021-06-05"),
                "kingdoms": ["Animalia", "Chromista"],
                "occurrence_statuses": {"present", "absent"},
                "exclusions": ["3 control/blank sample(s) excluded"],
            },
        ),
    ],
    ids=["minimal", "derived_box", "description_without_box", "project", "everything"],
)
def test_render_eml_xml_validates_against_the_vendored_xsd(manifest, options):
    xmlschema = pytest.importorskip("xmlschema")
    schema = xmlschema.XMLSchema(str(PACKAGE_DIR / "data" / "eml-xsd" / "eml.xsd"))
    schema.validate(_render_text(manifest(), **options))


def test_render_eml_xml_additional_metadata_is_a_sibling_of_dataset():
    root = _render(generated_at="2024-06-01T12:34:56Z")
    assert [c.tag for c in root] == ["dataset", "additionalMetadata"]
    assert (
        elements.child_text(root, "additionalMetadata/metadata/gbif/dateStamp")
        == "2024-06-01T12:34:56Z"
    )
    assert (
        elements.child_text(root, "additionalMetadata/metadata/gbif/hierarchyLevel") == "dataset"
    )


@pytest.mark.parametrize(
    ("statuses", "detection_limits", "convention"),
    [
        ({"present"}, [], PRESENCE_ONLY),
        ({"present"}, ["5 copies/reaction"], PRESENCE_ONLY),
        (
            {"present", "absent"},
            [],
            (
                f"{ABSENCES} An absence states only that no reads were counted: no pcr_primer_lod "
                "is recorded in this archive."
            ),
        ),
        (
            {"absent"},
            ["5 copies/reaction"],
            (
                f"{ABSENCES} An absence means the target was not detected above the assay's limit "
                "of detection, recorded as pcr_primer_lod: 5 copies/reaction."
            ),
        ),
    ],
)
def test_render_eml_xml_states_how_zero_counts_are_published(
    statuses, detection_limits, convention
):
    root = _render(occurrence_statuses=statuses, detection_limits=detection_limits)
    assert _method_paras(root) == [convention]


def test_render_eml_xml_puts_the_status_convention_and_exclusions_after_the_manifests_methods():
    root = _render(
        _with_methods("Sequenced on a MiSeq."),
        occurrence_statuses={"present"},
        exclusions=["3 control/blank sample(s) excluded", "1 Homo sapiens row(s) excluded"],
    )
    assert _method_paras(root) == [
        "Sequenced on a MiSeq.",
        PRESENCE_ONLY,
        (
            "Excluded before publishing: 3 control/blank sample(s) excluded; "
            "1 Homo sapiens row(s) excluded."
        ),
    ]
