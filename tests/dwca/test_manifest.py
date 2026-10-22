from __future__ import annotations


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

EML_22_DEFAULT_NS = """<?xml version="1.0"?>
<eml xmlns="https://eml.ecoinformatics.org/eml-2.2.0">
  <dataset>
    <title>An EML 2.2 Dataset</title>
  </dataset>
</eml>
"""


    m = Manifest()


    m = Manifest()


def test_ask_list_orders_title_and_license_first():
    m = Manifest()
    ask_list = m.ask_list()
    assert ask_list[0] == "title"
    assert ask_list[1] == "license"


def test_ask_list_omits_a_field_already_set():
    m = Manifest()
    assert "title" not in m.ask_list()


def test_scan_eml_reads_eml_2_1_1_namespaced_document(tmp_path):
    path = tmp_path / "eml.xml"
    path.write_text(EML_211, encoding="utf-8")
    assert found["title"] == "A Real Dataset Title"
    assert found["abstract"] == "A real abstract."
    assert found["geographic_description"] == "Monterey Bay, California"
    assert found["pub_date"] == "2023-01-01"


def test_scan_eml_reads_eml_2_2_default_namespaced_document(tmp_path):
    path = tmp_path / "eml.xml"
    path.write_text(EML_22_DEFAULT_NS, encoding="utf-8")


    (tmp_path / "eml.xml").write_text(EML_211, encoding="utf-8")
    result = init_scan(tmp_path)


def test_init_scan_with_no_eml_file_returns_an_empty_manifest(tmp_path):
    result = init_scan(tmp_path)
    assert result.manifest.values == {}
    assert result.manifest.ask_list()[0] == "title"


    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "eml.xml").write_text(EML_211, encoding="utf-8")
    (tmp_path / "b" / "eml.xml").write_text(EML_22_DEFAULT_NS, encoding="utf-8")

    result = init_scan(tmp_path)
