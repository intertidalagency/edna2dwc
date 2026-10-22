import json

import pytest

from edna2dwc.terms import sync
from edna2dwc.terms.term_table import load_term_table

SIMPLE_DWC_CSV = "occurrenceID\nscientificName\nbasisOfRecord\nkingdom\nmodified\ntype\n"

VERSIONS_CSV_HEADER = "term_localName,organized_in,status,term_iri\n"
VERSIONS_CSV_ROWS = (
    "occurrenceID,http://purl.org/dc/terms/Occurrence,recommended,http://rs.tdwg.org/dwc/terms/occurrenceID\n"
    "scientificName,http://purl.org/dc/terms/Taxon,recommended,http://rs.tdwg.org/dwc/terms/scientificName\n"
    "basisOfRecord,,recommended,http://rs.tdwg.org/dwc/terms/basisOfRecord\n"
    "kingdom,http://purl.org/dc/terms/Taxon,recommended,http://rs.tdwg.org/dwc/terms/kingdom\n"
    "modified,http://purl.org/dc/terms/,recommended,http://purl.org/dc/terms/modified\n"
    "type,http://purl.org/dc/elements/1.1/,recommended,http://purl.org/dc/elements/1.1/type\n"
    "measurementType,,recommended,http://rs.tdwg.org/dwc/terms/measurementType\n"
    "measurementValue,,recommended,http://rs.tdwg.org/dwc/terms/measurementValue\n"
    "occurrenceID,,superseded,http://rs.tdwg.org/dwc/terms/old/occurrenceID\n"
)
VERSIONS_CSV = VERSIONS_CSV_HEADER + VERSIONS_CSV_ROWS

DNA_DERIVED_XML = """<?xml version="1.0"?>
<extension xmlns="http://rs.gbif.org/extension/">
    <property name='samp_name' namespace='https://w3id.org/gensc/terms/'
        qualName='https://w3id.org/gensc/terms/MIXS:0001107' required='false'/>
    <property name='DNA_sequence' namespace='http://rs.gbif.org/terms/'
        qualName='http://rs.gbif.org/terms/dna_sequence' required='false'/>
    <property name='some_miqe_field' namespace='http://rs.gbif.org/terms/miqe/'
        qualName='http://rs.gbif.org/terms/miqe/some_miqe_field' required='false'/>
    <property name='ggbn_field' namespace='http://data.ggbn.org/schemas/ggbn/terms/'
        qualName='http://data.ggbn.org/schemas/ggbn/terms/ggbn_field' required='false'/>
</extension>
"""

EMOF_XML = """<?xml version="1.0"?>
<extension xmlns="http://rs.gbif.org/extension/">
    <property name='measurementID' namespace='http://rs.tdwg.org/dwc/terms/'
        qualName='http://rs.tdwg.org/dwc/terms/measurementID' required='false'/>
    <property name='measurementTypeID' namespace='http://rs.iobis.org/obis/terms/'
        qualName='http://rs.iobis.org/obis/terms/measurementTypeID' required='false'/>
</extension>
"""


def test_parse_dwc_and_dublin_core_resolves_uri_and_class():
    sources = sync.parse_dwc_and_dublin_core(SIMPLE_DWC_CSV, VERSIONS_CSV)
    by_name = {s.name: s for s in sources}
    assert by_name["occurrenceID"].uri == "http://rs.tdwg.org/dwc/terms/occurrenceID"
    assert by_name["occurrenceID"].term_class == "Occurrence"


def test_parse_dwc_and_dublin_core_bare_namespace_organized_in_is_record_level():
    sources = sync.parse_dwc_and_dublin_core(SIMPLE_DWC_CSV, VERSIONS_CSV)
    by_name = {s.name: s for s in sources}
    assert by_name["modified"].term_class == "record-level"
    assert by_name["type"].term_class == "record-level"
    assert by_name["basisOfRecord"].term_class == "record-level"


def test_parse_dwc_and_dublin_core_falls_back_for_names_missing_from_simple_list():
    sources = sync.parse_dwc_and_dublin_core(SIMPLE_DWC_CSV, VERSIONS_CSV)
    names = {s.name for s in sources}
    assert "measurementType" in names
    assert "measurementValue" in names


def test_parse_dwc_and_dublin_core_ignores_superseded_versions():
    sources = sync.parse_dwc_and_dublin_core(SIMPLE_DWC_CSV, VERSIONS_CSV)
    by_name = {s.name: s for s in sources}
    assert "old" not in by_name["occurrenceID"].uri


def test_parse_dna_derived_data_extension_covers_all_four_sub_namespaces():
    sources = sync.parse_dna_derived_data_extension(DNA_DERIVED_XML)
    names = {s.name for s in sources}
    assert names == {"samp_name", "DNA_sequence", "some_miqe_field", "ggbn_field"}
    assert all(s.term_class == "DNADerivedData" for s in sources)


def test_parse_emof_extension_keeps_only_obis_namespaced_properties():
    sources = sync.parse_emof_extension(EMOF_XML)
    assert [s.name for s in sources] == ["measurementTypeID"]
    assert sources[0].term_class == "MeasurementOrFact"


@pytest.mark.parametrize(
    ("name", "tier"),
    [
        ("occurrenceID", "required"),
        ("kingdom", "required_if_occurrence_core"),
        ("eventID", "required_if_event_core"),
        ("measurementType", "required_if_emof"),
        ("measurementUnit", "recommended"),
        ("someRandomOptionalTerm", "optional"),
    ],
)
def test_tier_for_returns_each_tier(name, tier):
    assert sync.tier_for(name) == tier


@pytest.mark.parametrize(
    ("name", "tier"),
    [
        ("annealingTemp", "required"),
        ("eventID", "strongly_recommended"),
        ("phylum", "recommended"),
        ("someRandomOptionalTerm", None),
    ],
)
def test_priority_tier_for_returns_each_tier(name, tier):
    assert sync.priority_tier_for(name) == tier


def test_build_term_table_attaches_priority_tier_only_when_applicable(monkeypatch):
    monkeypatch.setattr(sync, "ALL_TIERED_NAMES", frozenset({"occurrenceID", "samp_name"}))
    sources = [
        sync.TermSource(name="occurrenceID", uri="uri-a", term_class="Occurrence"),
        sync.TermSource(name="samp_name", uri="uri-b", term_class="DNADerivedData"),
    ]
    table = sync.build_term_table(sources)
    assert table["occurrenceID"]["priority_tier"] == "required"
    assert "priority_tier" not in table["samp_name"]


def test_build_term_table_applies_defaults(monkeypatch):
    monkeypatch.setattr(sync, "ALL_TIERED_NAMES", frozenset({"basisOfRecord", "occurrenceID"}))
    sources = sync.parse_dwc_and_dublin_core(
        SIMPLE_DWC_CSV, VERSIONS_CSV
    ) + sync.parse_emof_extension(EMOF_XML)
    table = sync.build_term_table(sources)
    assert table["basisOfRecord"]["default"] == "MaterialSample"
    assert "default" not in table["occurrenceID"]


def test_build_term_table_fails_closed_on_a_missing_tiered_term():
    sources = sync.parse_dwc_and_dublin_core(SIMPLE_DWC_CSV, VERSIONS_CSV)
    with pytest.raises(ValueError, match="eventID"):
        sync.build_term_table(sources)


def test_build_term_table_first_source_wins_on_name_collision(monkeypatch):
    monkeypatch.setattr(sync, "ALL_TIERED_NAMES", frozenset())
    a = sync.TermSource(name="dup", uri="uri-a", term_class="A")
    b = sync.TermSource(name="dup", uri="uri-b", term_class="B")
    table = sync.build_term_table([a, b])
    assert table["dup"]["uri"] == "uri-a"


def test_build_term_table_attaches_expects_field(monkeypatch):
    monkeypatch.setattr(sync, "ALL_TIERED_NAMES", frozenset({"decimalLatitude", "geodeticDatum"}))
    sources = [
        sync.TermSource(name="decimalLatitude", uri="uri-a", term_class="Location"),
        sync.TermSource(name="geodeticDatum", uri="uri-b", term_class="Location"),
        sync.TermSource(name="recordedBy", uri="uri-c", term_class="Occurrence"),
    ]
    table = sync.build_term_table(sources)
    assert {"then": "geodeticDatum", "severity": "warning"} in table["decimalLatitude"]["expects"]
    assert "expects" not in table["recordedBy"]


def test_build_term_table_attaches_pairs_field(monkeypatch):
    monkeypatch.setattr(sync, "ALL_TIERED_NAMES", frozenset({"sampleSizeValue", "sampleSizeUnit"}))
    sources = [
        sync.TermSource(name="sampleSizeValue", uri="uri-a", term_class="Occurrence"),
        sync.TermSource(name="sampleSizeUnit", uri="uri-b", term_class="Occurrence"),
        sync.TermSource(name="recordedBy", uri="uri-c", term_class="Occurrence"),
    ]
    table = sync.build_term_table(sources)
    assert table["sampleSizeValue"]["pairs"] == [{"with": "sampleSizeUnit", "severity": "error"}]
    assert "pairs" not in table["recordedBy"]


def test_step_writes_the_table_and_reports_the_count(tmp_path, monkeypatch):
    table = {
        "occurrenceID": {"uri": "http://rs.tdwg.org/dwc/terms/occurrenceID"},
        "_notes": {"term_count": 1},
    }
    monkeypatch.setattr(sync, "sync", lambda *a, **kw: table)
    output = tmp_path / "dwc_terms.json"

    result = sync.step(output=output)

    assert json.loads(output.read_text(encoding="utf-8")) == table
    assert "1 terms" in result.text
    assert result.outputs["term_table"] == str(output)
    assert result.exit_code == 0


def test_the_shipped_term_table_carries_the_rules_the_specs_declare():
    shipped = load_term_table()
    for name, entry in shipped.items():
        assert entry.get("expects") == sync.expects_for(name), name
        assert entry.get("pairs") == sync.pairs_for(name), name
