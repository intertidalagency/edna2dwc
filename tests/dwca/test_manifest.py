from __future__ import annotations

from edna2dwc.dwca.manifest import (
    BoundingBox,
    Manifest,
    Person,
    harvest_eml,
    init_scan,
)

EML_211 = """<?xml version="1.0"?>
<eml:eml xmlns:eml="eml://ecoinformatics.org/eml-2.1.1">
  <dataset>
    <title>A Real Dataset Title</title>
    <abstract><para>A real abstract.</para></abstract>
    <coverage>
      <geographicCoverage>
        <geographicDescription>Monterey Bay, California</geographicDescription>
      </geographicCoverage>
    </coverage>
    <pubDate>2023-01-01</pubDate>
  </dataset>
</eml:eml>
"""

EML_WITH_PEOPLE = """<?xml version="1.0"?>
<eml:eml xmlns:eml="eml://ecoinformatics.org/eml-2.1.1">
  <dataset>
    <title>A Real Dataset Title</title>
    <creator>
      <individualName><givenName>Jane</givenName><surName>Doe</surName></individualName>
      <organizationName>Example Foundation</organizationName>
      <electronicMailAddress>jane.doe@example.com</electronicMailAddress>
      <userId directory="https://orcid.org/">https://orcid.org/0000-0002-1825-0097</userId>
    </creator>
    <creator><organizationName>Example Institute</organizationName></creator>
    <creator><positionName>Data manager</positionName></creator>
    <coverage>
      <geographicCoverage>
        <geographicDescription>Example Inlet</geographicDescription>
        <boundingCoordinates>
          <westBoundingCoordinate>-123.14</westBoundingCoordinate>
          <eastBoundingCoordinate>-123.10</eastBoundingCoordinate>
          <northBoundingCoordinate>49.28</northBoundingCoordinate>
          <southBoundingCoordinate>49.26</southBoundingCoordinate>
        </boundingCoordinates>
      </geographicCoverage>
    </coverage>
    <contact>
      <individualName><surName>Doe</surName></individualName>
      <electronicMailAddress>jane.doe@example.com</electronicMailAddress>
    </contact>
  </dataset>
</eml:eml>
"""

EML_22_DEFAULT_NS = """<?xml version="1.0"?>
<eml xmlns="https://eml.ecoinformatics.org/eml-2.2.0">
  <dataset>
    <title>An EML 2.2 Dataset</title>
  </dataset>
</eml>
"""


def test_manifest_records_provenance_and_a_persons_reply():
    m = Manifest()
    m.set("title", "T", provenance="eml.xml title", confirmed="PI: yes")
    m.set_people("creators", [Person(surname="Lopez")], provenance="methods.pdf p. 1")
    assert m.provenance == {"title": "eml.xml title", "creators": "methods.pdf p. 1"}
    assert m.confirmed == {"title": "PI: yes"}


def test_a_blank_field_with_provenance_is_not_open_but_is_still_required():
    m = Manifest()
    m.leave_blank("license", provenance="waiting on the provider")
    assert not m.is_open("license")
    assert not m.is_set("license")
    assert "license" in m.blank_required()
    assert "license" not in m.ask_list()


def test_a_field_counts_as_set_once_it_has_a_value_of_any_shape():
    m = Manifest()
    m.set_people("contacts", [Person(surname="Lopez")], provenance="PI")
    m.set_bounding_box(BoundingBox(west=-1, south=-1, east=1, north=1), provenance="PI")
    assert m.is_set("contacts")
    assert m.is_set("bounding_box")
    assert not m.is_set("creators")


def test_ask_list_orders_title_and_license_first():
    m = Manifest()
    ask_list = m.ask_list()
    assert ask_list[0] == "title"
    assert ask_list[1] == "license"


def test_ask_list_omits_a_field_already_set():
    m = Manifest()
    m.set("title", "T", provenance="told me")
    assert "title" not in m.ask_list()


def test_scan_eml_reads_eml_2_1_1_namespaced_document(tmp_path):
    path = tmp_path / "eml.xml"
    path.write_text(EML_211, encoding="utf-8")
    found = harvest_eml(path).values
    assert found["title"] == "A Real Dataset Title"
    assert found["abstract"] == "A real abstract."
    assert found["geographic_description"] == "Monterey Bay, California"
    assert found["pub_date"] == "2023-01-01"


def test_scan_eml_reads_eml_2_2_default_namespaced_document(tmp_path):
    path = tmp_path / "eml.xml"
    path.write_text(EML_22_DEFAULT_NS, encoding="utf-8")
    assert harvest_eml(path).values["title"] == "An EML 2.2 Dataset"


def test_harvest_eml_reads_each_person_with_a_name_or_an_organization(tmp_path):
    path = tmp_path / "eml.xml"
    path.write_text(EML_WITH_PEOPLE, encoding="utf-8")
    harvested = harvest_eml(path)
    assert harvested.people["creators"] == [
        Person(
            given="Jane",
            surname="Doe",
            organization="Example Foundation",
            email="jane.doe@example.com",
            orcid="0000-0002-1825-0097",
        ),
        Person(organization="Example Institute"),
    ]
    assert harvested.people["contacts"] == [Person(surname="Doe", email="jane.doe@example.com")]
    assert harvested.provenance["creators"] == "eml.xml creators"
    assert harvested.provenance["contacts"] == "eml.xml contacts"


def test_harvest_eml_reads_the_bounding_box_by_name(tmp_path):
    path = tmp_path / "eml.xml"
    path.write_text(EML_WITH_PEOPLE, encoding="utf-8")
    harvested = harvest_eml(path)
    assert harvested.bounding_box == BoundingBox(
        west=-123.14, south=49.26, east=-123.10, north=49.28
    )
    assert harvested.provenance["bounding_box"] == "eml.xml bounding_box"


def test_init_scan_names_eml_xml_as_the_provenance_of_every_harvested_field(tmp_path):
    (tmp_path / "eml.xml").write_text(EML_211, encoding="utf-8")
    result = init_scan(tmp_path)
    assert result.manifest.provenance["title"] == "eml.xml title"
    assert result.manifest.provenance["abstract"] == "eml.xml abstract"
    assert result.eml_paths == [tmp_path / "eml.xml"]


def test_init_scan_with_no_eml_file_returns_an_empty_manifest(tmp_path):
    result = init_scan(tmp_path)
    assert result.manifest.values == {}
    assert result.manifest.ask_list()[0] == "title"


def test_init_scan_harvests_the_first_of_several_eml_files_and_names_them_all(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "eml.xml").write_text(EML_211, encoding="utf-8")
    (tmp_path / "b" / "eml.xml").write_text(EML_22_DEFAULT_NS, encoding="utf-8")

    result = init_scan(tmp_path)
    assert result.eml_paths == [tmp_path / "a" / "eml.xml", tmp_path / "b" / "eml.xml"]
    assert result.manifest.values["title"] == "A Real Dataset Title"
