


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
    )
    monkeypatch.setattr(ov, "candidate_polygons_for", lambda lat, lon: (long_edge_polygon,))
    monkeypatch.setattr(ov, "country_code_for", lambda lat, lon: "ZZ")
    assert ov.check_onland(-0.001, 0.0, buffer_degrees=0.01) == "ambiguous"


def test_check_onland_open_ocean_is_water():
    assert ov.check_onland(*OPEN_OCEAN) == "water"


def test_check_onland_unambiguous_inland_point_is_land():
    assert ov.check_onland(*LONDON) == "land"




def test_check_onland_habitat_hint_downgrades_to_ambiguous():


def test_check_onland_habitat_hint_with_no_nearshore_keyword_stays_land():


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
    on_land = [f for f in log.findings if "ON_LAND" in f.message]


def test_run_obis_validation_applies_an_accepted_adjudication():
    header = ["occurrenceID", "decimalLatitude", "decimalLongitude"]
    rows = [{"decimalLatitude": str(LONDON[0]), "decimalLongitude": str(LONDON[1])}]


def test_run_obis_validation_issues_out_collects_the_real_category():
    header = ["occurrenceID", "decimalLatitude", "decimalLongitude"]
    rows = [{"decimalLatitude": str(LONDON[0]), "decimalLongitude": str(LONDON[1])}]
    issues_out = []
    assert issues_out == ["ON_LAND"]


def test_run_obis_validation_issues_out_omits_an_accepted_adjudication():
    header = ["occurrenceID", "decimalLatitude", "decimalLongitude"]
    rows = [{"decimalLatitude": str(LONDON[0]), "decimalLongitude": str(LONDON[1])}]
    issues_out = []
    ov.run_obis_validation(
    )
    assert issues_out == []


def test_run_obis_validation_no_finding_when_no_coordinates_present():
    log = ov.run_obis_validation(
        ["minimumDepthInMeters", "maximumDepthInMeters"],
    )
    assert log.findings == []
