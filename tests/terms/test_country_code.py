from __future__ import annotations

import pytest

from edna2dwc.terms.country_code import (
    NEARBY_COUNTRY_KM,
    BoundaryPolygon,
    candidate_polygons_for,
    country_code_for,
    distance_to_nearby_ring_km,
    place_in_country,
    valid_country_codes,
)


def test_candidate_polygons_for_a_coastal_point_includes_the_matching_country():
    candidates = candidate_polygons_for(37.495306, -122.498744)
    assert any(poly.iso_a2 == "US" for poly in candidates)


def test_candidate_polygons_for_open_water_can_be_empty():
    candidates = candidate_polygons_for(0.0, -140.0)
    assert candidates == ()


def test_country_code_for_resolves_the_same_point_on_either_side_of_the_seam():
    assert country_code_for(71.0, 180.0) == country_code_for(71.0, -180.0) == "RU"


def test_country_code_for_resolves_a_0_360_convention_longitude():
    assert country_code_for(66.0, 185.0) == country_code_for(66.0, -175.0) == "RU"
    assert country_code_for(66.0, -185.0) == country_code_for(66.0, 175.0) == "RU"


def test_a_code_is_valid_without_a_land_polygon_for_its_country():
    assert {"TC", "XK", "US"} <= valid_country_codes()


@pytest.mark.parametrize(
    ("lat", "lon", "code"),
    [
        (42.30, -83.03, "CA"),
        (-29.31, 27.48, "LS"),
        (43.94, 12.45, "SM"),
        (41.9033, 12.4535, "VA"),
        (43.7395, 7.425, "MC"),
        (36.13, -5.348, "GI"),
        (22.35, 114.18, "HK"),
        (1.29, 103.85, "SG"),
    ],
)
def test_country_code_for_resolves_small_states_and_enclaves(lat, lon, code):
    assert country_code_for(lat, lon) == code


@pytest.mark.parametrize(("lat", "lon"), [(-29.31, 27.48), (43.94, 12.45), (41.9033, 12.4535)])
def test_an_enclave_lies_in_no_polygon_of_the_country_around_it(lat, lon):
    containing = [p.iso_a2 for p in candidate_polygons_for(lat, lon) if p.contains(lat, lon)]
    assert len(containing) == 1


def test_a_point_in_a_hole_is_outside_the_polygon():
    outer = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0))
    hole = ((1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0))
    polygon = BoundaryPolygon(iso_a2="XX", bbox=(0.0, 0.0, 4.0, 4.0), rings=(outer, hole))
    assert polygon.contains(0.5, 0.5)
    assert not polygon.contains(2.0, 2.0)


def test_a_point_on_land_is_placed_in_its_country_at_no_distance():
    placement = place_in_country(37.495306, -122.498744)
    assert placement is not None
    assert (placement.iso_a2, placement.distance_km) == ("US", 0.0)


def test_a_point_in_monterey_bay_is_placed_in_the_country_of_the_nearby_coast():
    placement = place_in_country(36.7933, -121.8383)
    assert placement is not None
    assert placement.iso_a2 == "US"
    assert 0 < placement.distance_km <= NEARBY_COUNTRY_KM


@pytest.mark.parametrize(("lat", "lon"), [(36.5, -123.0), (0.0, -140.0)])
def test_a_point_farther_than_the_distance_from_every_coast_is_placed_nowhere(lat, lon):
    assert place_in_country(lat, lon) is None


def test_the_nearest_of_two_coasts_names_the_country():
    placement = place_in_country(35.95, -5.5)
    assert placement is not None
    assert placement.iso_a2 == "MA"


def test_a_distance_is_measured_on_the_sphere():
    meridian = ((0.1, -1.0), (0.1, 1.0))
    assert distance_to_nearby_ring_km(0.0, 0.0, meridian) == pytest.approx(11.12, abs=0.01)
    assert distance_to_nearby_ring_km(60.0, 0.0, ((0.2, 59.0), (0.2, 61.0))) == pytest.approx(
        11.12, abs=0.05
    )


def test_a_ring_with_no_edge_within_the_distance_is_infinitely_far():
    assert distance_to_nearby_ring_km(0.0, 0.0, ((1.0, -1.0), (1.0, 1.0))) == float("inf")


def test_a_distance_is_measured_across_the_antimeridian():
    across_the_seam = ((-179.95, -1.0), (-179.95, 1.0))
    assert distance_to_nearby_ring_km(0.0, 179.95, across_the_seam) == pytest.approx(
        11.12, abs=0.01
    )
    assert distance_to_nearby_ring_km(
        0.0, -179.95, ((179.95, -1.0), (179.95, 1.0))
    ) == pytest.approx(11.12, abs=0.01)


def test_a_point_near_the_antimeridian_is_placed_the_same_from_either_side():
    east, west = place_in_country(-16.6, 180.0), place_in_country(-16.6, -180.0)
    assert east == west
    assert east is not None
    assert east.iso_a2 == "FJ"
