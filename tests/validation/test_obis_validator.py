from edna2dwc.terms.country_code import BoundaryPolygon
from edna2dwc.validation import obis_validator as ov
from tests.tables import table_of

PILLAR_POINT_HARBOR = (37.495306, -122.498744)
LONDON = (51.5074, -0.1278)
OPEN_OCEAN = (0.0, -140.0)


def test_is_nearshore_habitat_hint_matches_known_keywords():
    assert ov.is_nearshore_habitat_hint("rocky intertidal")
    assert ov.is_nearshore_habitat_hint("Coastal lagoon")
    assert not ov.is_nearshore_habitat_hint("deciduous forest")


def test_is_nearshore_habitat_hint_matches_bare_keywords_without_intertidal():
    assert ov.is_nearshore_habitat_hint("mudflat")
    assert ov.is_nearshore_habitat_hint("salt marsh")
    assert ov.is_nearshore_habitat_hint("littoral zone")
    assert ov.is_nearshore_habitat_hint("mangrove forest")
    assert ov.is_nearshore_habitat_hint("rocky reef")
    assert ov.is_nearshore_habitat_hint("rocky shore")


def test_is_nearshore_habitat_hint_does_not_match_offshore_or_inshore():
    assert not ov.is_nearshore_habitat_hint("offshore")
    assert not ov.is_nearshore_habitat_hint("Offshore pelagic")


def test_check_onland_buffer_catches_a_point_mid_edge_not_just_near_a_vertex(monkeypatch):
    long_edge_polygon = BoundaryPolygon(
        iso_a2="ZZ",
        bbox=(-1.0, -1.0, 1.0, 1.0),
        rings=(((-1.0, 0.0), (1.0, 0.0), (1.0, -1.0), (-1.0, -1.0)),),
    )
    monkeypatch.setattr(ov, "candidate_polygons_for", lambda lat, lon: (long_edge_polygon,))
    monkeypatch.setattr(ov, "country_code_for", lambda lat, lon: "ZZ")
    assert ov.check_onland(-0.001, 0.0, buffer_degrees=0.01) == "ambiguous"


def test_check_onland_open_ocean_is_water():
    assert ov.check_onland(*OPEN_OCEAN) == "water"


def test_check_onland_unambiguous_inland_point_is_land():
    assert ov.check_onland(*LONDON) == "land"


def test_check_onland_a_harbor_point_near_the_coastline_is_ambiguous():
    assert ov.check_onland(*PILLAR_POINT_HARBOR) == "ambiguous"


def test_check_onland_habitat_hint_downgrades_to_ambiguous():
    assert ov.check_onland(*LONDON, habitat="rocky intertidal") == "ambiguous"


def test_check_onland_habitat_hint_with_no_nearshore_keyword_stays_land():
    assert ov.check_onland(*LONDON, habitat="deciduous forest") == "land"


def test_check_onland_for_rows_counts_land_and_ambiguous_separately():
    rows = [
        {
            "decimalLatitude": str(LONDON[0]),
            "decimalLongitude": str(LONDON[1]),
        },
        {
            "decimalLatitude": str(PILLAR_POINT_HARBOR[0]),
            "decimalLongitude": str(PILLAR_POINT_HARBOR[1]),
            "habitat": "intertidal mudflat",
        },
        {
            "decimalLatitude": str(OPEN_OCEAN[0]),
            "decimalLongitude": str(OPEN_OCEAN[1]),
        },
        {"decimalLatitude": "", "decimalLongitude": ""},
    ]
    summary = ov.check_onland_for_rows(table_of(rows))
    assert summary.land_count == 1
    assert summary.ambiguous_count == 1


def test_check_recommended_fields_flags_both_missing_depth_terms():
    log = ov.check_recommended_fields(["occurrenceID", "scientificName"])
    assert len(log.findings) == 2
    assert all(f.code == "OBIS_VALIDATOR_ISSUE" for f in log.findings)
    assert all(f.severity == "warning" for f in log.findings)


def test_check_recommended_fields_empty_when_both_present():
    log = ov.check_recommended_fields(["minimumDepthInMeters", "maximumDepthInMeters"])
    assert log.findings == []


def test_run_obis_validation_reports_on_land_as_an_error():
    header = ["occurrenceID", "decimalLatitude", "decimalLongitude"]
    rows = [{"decimalLatitude": str(LONDON[0]), "decimalLongitude": str(LONDON[1])}]
    log = ov.run_obis_validation(header, table_of(rows))
    on_land = [f for f in log.findings if "ON_LAND" in f.message]
    assert [(f.code, f.severity) for f in on_land] == [("ADJUDICATION_NEEDED", "error")]


def test_run_obis_validation_applies_an_accepted_adjudication():
    header = ["occurrenceID", "decimalLatitude", "decimalLongitude"]
    rows = [{"decimalLatitude": str(LONDON[0]), "decimalLongitude": str(LONDON[1])}]
    log = ov.run_obis_validation(header, table_of(rows), adjudications={"ON_LAND": "accepted"})
    on_land = [f for f in log.findings if "ON_LAND" in f.message]
    assert [(f.code, f.message) for f in on_land] == [
        (
            "STRUCTURAL_COST_DISCLOSED",
            "OBIS ON_LAND: 1 record(s), accepted as a disclosed structural cost",
        )
    ]


def test_run_obis_validation_issues_out_collects_the_real_category():
    header = ["occurrenceID", "decimalLatitude", "decimalLongitude"]
    rows = [{"decimalLatitude": str(LONDON[0]), "decimalLongitude": str(LONDON[1])}]
    issues_out = []
    ov.run_obis_validation(header, table_of(rows), issues_out=issues_out)
    assert issues_out == ["ON_LAND"]


def test_run_obis_validation_issues_out_omits_an_accepted_adjudication():
    header = ["occurrenceID", "decimalLatitude", "decimalLongitude"]
    rows = [{"decimalLatitude": str(LONDON[0]), "decimalLongitude": str(LONDON[1])}]
    issues_out = []
    ov.run_obis_validation(
        header, table_of(rows), adjudications={"ON_LAND": "accepted"}, issues_out=issues_out
    )
    assert issues_out == []


def test_run_obis_validation_no_finding_when_no_coordinates_present():
    log = ov.run_obis_validation(
        ["minimumDepthInMeters", "maximumDepthInMeters"],
        table_of([{"minimumDepthInMeters": "1", "maximumDepthInMeters": "2"}]),
    )
    assert log.findings == []


def _name_id_findings(*name_ids: str) -> list:
    header = ["minimumDepthInMeters", "maximumDepthInMeters", "scientificNameID"]
    rows = [{"scientificNameID": name_id} for name_id in name_ids]
    return ov.run_obis_validation(header, table_of(rows)).findings


def test_a_name_identified_only_by_gbif_is_reported_as_one_obis_drops():
    [finding] = _name_id_findings(
        "https://www.gbif.org/species/4321", "urn:lsid:marinespecies.org:taxname:132064"
    )
    assert finding.code == "OBIS_VALIDATOR_ISSUE"
    assert finding.severity == "warning"
    assert finding.count == 1


def test_names_identified_by_worms_raise_nothing():
    assert _name_id_findings("urn:lsid:marinespecies.org:taxname:132064") == []
