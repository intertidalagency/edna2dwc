from maintenance.boundaries import _country_code, build_boundary_set


def test_country_code_prefers_iso_a2_when_well_formed():
    assert _country_code({"ISO_A2": "US", "ISO_A2_EH": "US"}) == "US"


def test_country_code_falls_back_to_iso_a2_eh_when_iso_a2_is_the_sentinel():
    assert _country_code({"ISO_A2": "-99", "ISO_A2_EH": "FR"}) == "FR"


def test_country_code_falls_back_to_iso_a2_eh_when_iso_a2_is_not_two_letters():
    assert _country_code({"ISO_A2": "CN-TW", "ISO_A2_EH": "TW"}) == "TW"


def test_country_code_returns_none_when_neither_field_is_well_formed():
    assert _country_code({"ISO_A2": "-99", "ISO_A2_EH": "-99"}) is None
    assert _country_code({}) is None


def test_build_boundary_set_never_emits_a_malformed_country_code():
    geojson = {
        "features": [
            {
                "properties": {"ADMIN": "Taiwan", "ISO_A2": "CN-TW", "ISO_A2_EH": "TW"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[120.0, 22.0], [121.0, 22.0], [121.0, 25.0], [120.0, 22.0]]],
                },
            }
        ]
    }
    records = build_boundary_set(geojson)
    assert [r["iso_a2"] for r in records] == ["TW"]
