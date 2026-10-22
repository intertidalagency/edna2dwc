from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pytest

from edna2dwc.build import derive_fields
from edna2dwc.build.derive_fields import (
    _published_at,
    check_coordinate_signs,
    check_zero_counts,
    country_and_footprint,
    disclose_generalizations,
    report_reads_excluded_from_totals,
    resolve_conflicting_timestamps,
    status_and_quantities,
)
from edna2dwc.build.sheets import RowsChanged, SheetRefused
from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import Table, read_tsv
from tests.tables import dicts, table_of

NEARSHORE = {"decimalLatitude": "36.7933", "decimalLongitude": "-121.8383"}
POINT_REYES = {"decimalLatitude": "37.495306", "decimalLongitude": "-122.498744"}
WINDSOR = {"decimalLatitude": "42.30", "decimalLongitude": "-83.03"}
OFFSHORE = {"decimalLatitude": "0", "decimalLongitude": "-140"}


@dataclass
class _Step:
    rows: list[dict[str, str]]
    findings: FindingsLog


def _quantities(rows, **options):
    table, findings = status_and_quantities(table_of(rows), "step", **options)
    return _Step(dicts(table), findings)


def _placed(rows):
    table, findings = country_and_footprint(table_of(rows), "step")
    return _Step(dicts(table), findings)


def _timestamps(rows, *, col_a, col_b):
    table, findings = resolve_conflicting_timestamps(
        table_of(rows), "step", col_a=col_a, col_b=col_b
    )
    return _Step(dicts(table), findings)


def _signs(rows):
    return _Step([], check_coordinate_signs(table_of(rows)))


def _disclosed_table(table: Table) -> _Step:
    return _Step(dicts(disclose_generalizations(table, "step")), FindingsLog())


def _disclosed(rows):
    return _disclosed_table(table_of(rows))


@pytest.mark.parametrize("count", [{"count": ""}, {"count": "NA"}, {}])
def test_a_missing_count_leaves_occurrence_status_blank_not_fabricated(count):
    result = _quantities([{"sampleID": "S1", "featureID": "f1", **count}])
    assert result.rows[0]["occurrenceStatus"] == ""
    assert any(f.code == "TERM_MISSING_PRIORITY" for f in result.findings.findings)


def test_zero_counts_are_refused_with_one_finding_that_counts_them():
    rows = [
        {"sampleID": "S1", "featureID": f"f{i}", "count": "0" if i % 2 else "3"} for i in range(10)
    ]
    (refused,) = check_zero_counts(table_of(rows), emit_absences=False).findings
    assert refused.code == "ZERO_COUNTS_KEPT"
    assert refused.count == 5


def test_zero_counts_are_accepted_when_absences_are_published():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "0"}]
    assert check_zero_counts(table_of(rows), emit_absences=True).findings == []


def test_a_positive_count_is_present_with_quantity_and_type():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "42"}]
    result = _quantities(rows)
    row = result.rows[0]
    assert row["occurrenceStatus"] == "present"
    assert row["organismQuantity"] == "42"
    assert row["organismQuantityType"] == "DNA sequence reads"


def test_a_marker_quantity_type_labels_both_the_quantity_and_the_sample_size():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "0.25", "marker": "qPCR"},
        {"sampleID": "S1", "featureID": "f2", "count": "12", "marker": "16S"},
    ]
    result = _quantities(rows, quantity_types={"qPCR": "copies per litre"})
    by_marker = {row["marker"]: row for row in result.rows}
    assert by_marker["qPCR"]["organismQuantityType"] == "copies per litre"
    assert by_marker["16S"]["organismQuantityType"] == "DNA sequence reads"
    assert by_marker["16S"]["sampleSizeUnit"] == "DNA sequence reads"


def test_a_count_that_is_not_reads_gets_no_derived_sample_size():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "0.25"},
        {"sampleID": "S1", "featureID": "f2", "count": "0.5"},
    ]
    result = _quantities(rows, quantity_types={"": "relative abundance"})
    assert not any(row.get("sampleSizeValue") for row in result.rows)
    assert not any(row.get("sampleSizeUnit") for row in result.rows)


def test_a_supplied_sample_size_is_kept_whatever_the_count_measures():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "0.25", "sampleSizeValue": "3"}]
    result = _quantities(rows, quantity_types={"": "relative abundance"})
    assert result.rows[0]["sampleSizeValue"] == "3"


def test_sample_size_is_the_per_sample_read_total():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "10"},
        {"sampleID": "S1", "featureID": "f2", "count": "15"},
        {"sampleID": "S2", "featureID": "f1", "count": "5"},
    ]
    result = _quantities(rows)
    by_feature = {(r["sampleID"], r["featureID"]): r for r in result.rows}
    assert by_feature[("S1", "f1")]["sampleSizeValue"] == "25"
    assert by_feature[("S1", "f1")]["sampleSizeUnit"] == "DNA sequence reads"
    assert by_feature[("S2", "f1")]["sampleSizeValue"] == "5"


def test_a_coastal_coordinate_resolves_a_real_country_code():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "decimalLatitude": "37.495306",
            "decimalLongitude": "-122.498744",
        }
    ]
    result = _placed(rows)
    assert result.rows[0]["countryCode"] == "US"


def test_a_mid_ocean_coordinate_is_a_justified_blank_never_a_guess():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "decimalLatitude": "0",
            "decimalLongitude": "-140",
        }
    ]
    result = _placed(rows)
    assert "countryCode" not in result.rows[0]
    assert any(
        f.code == "TERM_MISSING_PRIORITY" and "countryCode" in f.message
        for f in result.findings.findings
    )


def test_offshore_coordinates_are_reported_once_with_a_count_and_each_coordinate():
    rows = [
        {"sampleID": sample, "decimalLatitude": lat, "decimalLongitude": "-140"}
        for sample, lat in (("S1", "0"), ("S2", "0"), ("S3", "1"))
    ]
    result = _placed(rows)
    offshore = [f for f in result.findings.findings if f.code == "TERM_MISSING_PRIORITY"]
    assert len(offshore) == 1
    assert offshore[0].count == 3
    assert "(0.0, -140.0)" in offshore[0].message
    assert "(1.0, -140.0)" in offshore[0].message


def test_a_nearshore_coordinate_takes_the_nearby_coast_country_and_is_reported_once():
    rows = [
        {"sampleID": sample, "decimalLatitude": lat, "decimalLongitude": "-121.8383"}
        for sample, lat in (("S1", "36.7933"), ("S2", "36.7933"), ("S3", "36.7948"))
    ]
    result = _placed(rows)
    assert [r["countryCode"] for r in result.rows] == ["US", "US", "US"]
    [nearby] = [f for f in result.findings.findings if f.code == "COUNTRY_CODE_FROM_NEARBY_COAST"]
    assert nearby.count == 3
    assert "(36.7933, -121.8383) is 4.0 km from US" in nearby.message
    assert not [f for f in result.findings.findings if f.code == "TERM_MISSING_PRIORITY"]


def test_each_distinct_coordinate_is_placed_once(monkeypatch):
    placed = []

    def place(lat, lon):
        placed.append((lat, lon))

    monkeypatch.setattr(derive_fields, "place_in_country", place)
    rows = [{"decimalLatitude": lat, "decimalLongitude": "-140"} for lat in ("0", "0", "1", "0.0")]
    _placed(rows)
    assert sorted(placed) == [(0.0, -140.0), (1.0, -140.0)]


def test_no_coordinate_columns_leaves_a_country_code_blank_and_reports_it():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "1"}]
    result = _placed(rows)
    assert "countryCode" not in result.rows[0]
    [blank] = [f for f in result.findings.findings if f.code == "TERM_MISSING_PRIORITY"]
    assert blank.count == 1
    assert "no coordinates" in blank.message


def _row(lon, sample_id="S1"):
    return {
        "sampleID": sample_id,
        "featureID": "f1",
        "count": "1",
        "decimalLatitude": "45.0",
        "decimalLongitude": str(lon),
    }


def test_a_minority_sign_flip_is_flagged_not_silently_corrected():
    rows = [_row(-70.0, f"S{i}") for i in range(9)] + [_row(70.0, "S_odd")]
    result = _signs(rows)
    codes = [f.code for f in result.findings.findings]
    assert codes == ["COORDINATE_SIGN_SUSPECT"]
    assert "decimalLongitude" in result.findings.findings[0].message


def test_a_uniform_sign_convention_raises_nothing():
    rows = [_row(-70.0, f"S{i}") for i in range(10)]
    result = _signs(rows)
    assert result.findings.findings == []


def test_latitude_and_longitude_are_flagged_independently():
    rows = [
        {
            "sampleID": f"S{i}",
            "featureID": "f1",
            "count": "1",
            "decimalLatitude": "45.0",
            "decimalLongitude": "-70.0",
        }
        for i in range(9)
    ]
    rows.append(
        {
            "sampleID": "S_odd",
            "featureID": "f1",
            "count": "1",
            "decimalLatitude": "-45.0",
            "decimalLongitude": "70.0",
        }
    )
    result = _signs(rows)
    messages = [f.message for f in result.findings.findings]
    assert len(messages) == 2
    assert any(m.startswith("decimalLatitude") for m in messages)
    assert any(m.startswith("decimalLongitude") for m in messages)


def test_a_point_footprint_names_the_datum_of_the_coordinates_it_repeats():
    rows = [{"decimalLatitude": "45.0", "decimalLongitude": "-70.0", "geodeticDatum": "EPSG:4326"}]
    row = _placed(rows).rows[0]
    assert row["footprintWKT"] == "POINT (-70.0 45.0)"
    assert row["footprintSRS"] == "EPSG:4326"


def test_a_point_footprint_without_a_datum_has_no_srs():
    rows = [{"decimalLatitude": "45.0", "decimalLongitude": "-70.0"}]
    row = _placed(rows).rows[0]
    assert row["footprintWKT"] == "POINT (-70.0 45.0)"
    assert not row.get("footprintSRS")


def test_a_source_footprint_is_kept_and_takes_the_rows_datum_as_its_srs():
    line = "LINESTRING (-70.1 45.0, -70.2 45.1)"
    rows = [
        {
            "decimalLatitude": "45.0",
            "decimalLongitude": "-70.0",
            "geodeticDatum": "EPSG:4326",
            "footprintWKT": line,
        }
    ]
    row = _placed(rows).rows[0]
    assert row["footprintWKT"] == line
    assert row["footprintSRS"] == "EPSG:4326"


def test_a_source_footprint_srs_is_never_replaced():
    rows = [
        {
            "geodeticDatum": "EPSG:4326",
            "footprintWKT": "POINT (-70.0 45.0)",
            "footprintSRS": "EPSG:4269",
        }
    ]
    assert _placed(rows).rows[0]["footprintSRS"] == "EPSG:4269"


def test_no_footprint_without_coordinates():
    rows = [{"sampleID": "S1", "geodeticDatum": "EPSG:4326"}]
    assert "footprintWKT" not in _placed(rows).rows[0]


def test_a_point_footprint_fills_a_row_whose_column_exists_but_is_blank():
    rows = [
        {
            "decimalLatitude": "45.0",
            "decimalLongitude": "-70.0",
            "geodeticDatum": "WGS84",
            "footprintWKT": "",
        }
    ]
    assert _placed(rows).rows[0]["footprintWKT"] == "POINT (-70.0 45.0)"


def test_conflicting_timestamps_are_disclosed_and_both_preserved():
    rows = [
        {
            "sampleID": "S1",
            "date_field_survey": "2023-08-01T10:00:00",
            "date_lab_log": "2023-08-01T11:30:00",
        }
    ]
    result = _timestamps(rows, col_a="date_field_survey", col_b="date_lab_log")
    assert "verbatimEventDate" in result.rows[0]
    assert "10:00:00" in result.rows[0]["verbatimEventDate"]
    assert "11:30:00" in result.rows[0]["verbatimEventDate"]
    codes = [f.code for f in result.findings.findings]
    assert "TIMESTAMP_CONFLICT" in codes
    assert "date_field_survey" in result.findings.findings[0].message


def test_agreeing_timestamps_raise_nothing():
    rows = [{"sampleID": "S1", "a": "2023-08-01", "b": "2023-08-01"}]
    result = _timestamps(rows, col_a="a", col_b="b")
    assert result.findings.findings == []
    assert "verbatimEventDate" not in result.rows[0]


def test_sample_size_is_per_marker_when_a_marker_column_is_present():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "marker": "16S", "count": "10"},
        {"sampleID": "S1", "featureID": "f2", "marker": "16S", "count": "15"},
        {"sampleID": "S1", "featureID": "f3", "marker": "COI", "count": "100"},
        {"sampleID": "S1", "featureID": "f4", "marker": "18S", "count": "7"},
    ]
    result = _quantities(rows)
    by_feature = {r["featureID"]: r for r in result.rows}
    assert by_feature["f1"]["sampleSizeValue"] == "25"
    assert by_feature["f2"]["sampleSizeValue"] == "25"
    assert by_feature["f3"]["sampleSizeValue"] == "100"
    assert by_feature["f4"]["sampleSizeValue"] == "7"


def test_a_sample_id_carrying_several_markers_is_disclosed():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "marker": "16S", "count": "10"},
        {"sampleID": "S1", "featureID": "f2", "marker": "COI", "count": "100"},
    ]
    result = _quantities(rows)
    assert any(f.code == "SAMPLE_SIZE_PER_MARKER" for f in result.findings.findings)


def test_a_table_with_no_marker_column_discloses_the_unverifiable_denominator():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "10"},
        {"sampleID": "S1", "featureID": "f2", "count": "100"},
    ]
    result = _quantities(rows)
    ungrouped = [f for f in result.findings.findings if f.code == "SAMPLE_SIZE_UNGROUPED"]
    assert ungrouped


def test_a_supplied_sample_size_survives_and_its_disagreement_with_the_total_is_reported():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "10", "sampleSizeValue": "136859"},
        {"sampleID": "S1", "featureID": "f2", "count": "15"},
    ]
    result = _quantities(rows)
    by_feature = {r["featureID"]: r for r in result.rows}
    assert by_feature["f1"]["sampleSizeValue"] == "136859"
    assert by_feature["f2"]["sampleSizeValue"] == "25"
    assert any(f.code == "SAMPLE_SIZE_SUPPLIED" for f in result.findings.findings)
    disagreements = [f for f in result.findings.findings if f.code == "SAMPLE_SIZE_DISAGREEMENT"]
    assert disagreements
    assert "S1" in disagreements[0].message
    assert disagreements[0].severity == "warning"


def test_a_blank_marker_on_one_row_groups_that_row_on_its_own_and_is_reported():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "marker": "16S", "count": "10"},
        {"sampleID": "S1", "featureID": "f2", "marker": "", "count": "100"},
    ]
    result = _quantities(rows)
    by_feature = {r["featureID"]: r for r in result.rows}
    assert by_feature["f1"]["sampleSizeValue"] == "10"
    assert by_feature["f2"]["sampleSizeValue"] == "100"
    incomplete = [f for f in result.findings.findings if f.code == "MARKER_INCOMPLETE"]
    assert incomplete
    assert "S1" in incomplete[0].message
    assert not [f for f in result.findings.findings if f.code == "SAMPLE_SIZE_PER_MARKER"]


def test_one_library_agreeing_on_a_supplied_denominator_is_not_a_disagreement():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "10", "sampleSizeValue": "25"},
        {"sampleID": "S1", "featureID": "f2", "count": "15", "sampleSizeValue": "25.0"},
    ]
    result = _quantities(rows)
    assert not [f for f in result.findings.findings if f.code == "SAMPLE_SIZE_DISAGREEMENT"]


def test_a_supplied_sample_size_keeps_no_unit_and_is_reported_without_one():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10", "sampleSizeValue": "2.5"}]
    result = _quantities(rows)
    assert result.rows[0].get("sampleSizeUnit", "") == ""
    unitless = [f for f in result.findings.findings if f.code == "TERM_PAIR_INCOMPLETE"]
    assert unitless
    assert "sampleSizeUnit" in unitless[0].message


def _generalization(row: dict[str, str]) -> str:
    return _disclosed([row]).rows[0].get("dataGeneralizations", "")


@pytest.mark.parametrize(
    "row",
    [
        {"sampleID": "S1", "scientificName": "Aaptos"},
        {"sampleID": "S1", "scientificName": "Animalia", "verbatimIdentification": "unassigned"},
        {
            "sampleID": "S1",
            "scientificName": "Flavobacterium",
            "genus": "Flavobacterium",
            "verbatimIdentification": "uncultured_marine",
        },
        {"sampleID": "S1", "scientificName": "Aaptos", "resolution_path": "leaf"},
    ],
)
def test_a_row_with_nothing_to_disclose_carries_no_data_generalizations(row):
    assert _generalization(row) == ""


def test_a_placeholder_row_says_it_could_not_be_identified():
    generalization = _generalization({"sampleID": "S1", "scientificName": "Biota incertae sedis"})
    assert generalization
    assert "identificationRemarks" not in generalization
    assert "verbatimIdentification" not in generalization


@pytest.mark.parametrize(
    ("row", "named"),
    [
        (
            {
                "scientificName": "Biota",
                "identificationRemarks": "no confident match below phylum",
            },
            "identificationRemarks",
        ),
        (
            {"scientificName": "Biota incertae sedis", "verbatimIdentification": "NA"},
            "verbatimIdentification",
        ),
        (
            {
                "scientificName": "Leucoraja",
                "taxonRank": "Genus",
                "resolution_path": "compound_common_ancestor",
            },
            "Leucoraja",
        ),
        (
            {
                "scientificName": "Biota incertae sedis",
                "resolution_path": "compound_common_ancestor",
            },
            "placeholder",
        ),
    ],
)
def test_a_generalized_row_names_what_was_generalized(row, named):
    assert named in _generalization({"sampleID": "S1", **row})


def test_data_generalizations_are_per_row():
    rows = [
        {"sampleID": "S1", "scientificName": "Biota incertae sedis"},
        {"sampleID": "S2", "scientificName": "Aaptos"},
    ]
    result = _disclosed(rows)
    assert result.rows[0]["dataGeneralizations"]
    assert not result.rows[1].get("dataGeneralizations")


def test_disclosure_fields_survive_a_short_row_with_no_scientific_name_cell(tmp_path):
    path = tmp_path / "rows.tsv"
    path.write_text("sampleID\tscientificName\nS1\n", encoding="utf-8")
    result = _disclosed_table(read_tsv(duckdb.connect(), path, "source"))
    assert not result.rows[0].get("dataGeneralizations")


def test_a_record_backed_off_to_a_higher_rank_says_where_it_was_published():
    row = {
        "sampleID": "S1",
        "scientificName": "Bacteroidales",
        "taxonRank": "Order",
        "resolution_path": "rank_backoff",
    }
    generalization = _generalization(row)
    assert "order Bacteroidales" in generalization
    assert "placeholder" not in generalization


def test_a_backed_off_record_with_no_rank_names_the_taxon_alone():
    row = {"sampleID": "S1", "scientificName": "Bacteria", "resolution_path": "rank_backoff"}
    assert _published_at(row) == "Bacteria"


@pytest.mark.parametrize(
    ("counts", "total"),
    [(("100", "200"), "300"), (("0.25", "0.5"), "0.75"), (("0.1", "0.2"), "0.3")],
)
def test_a_library_total_is_written_without_a_needless_fraction_or_floating_point_noise(
    counts, total
):
    rows = [
        {"sampleID": "S1", "featureID": f"f{n}", "count": count} for n, count in enumerate(counts)
    ]
    assert {r["sampleSizeValue"] for r in _quantities(rows).rows} == {total}


def test_a_non_finite_count_is_treated_as_no_count():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "nan"},
        {"sampleID": "S1", "featureID": "f2", "count": "inf"},
        {"sampleID": "S1", "featureID": "f3", "count": "10"},
    ]
    result = _quantities(rows)
    by_feature = {r["featureID"]: r for r in result.rows}
    assert by_feature["f1"]["occurrenceStatus"] == ""
    assert by_feature["f2"]["occurrenceStatus"] == ""
    assert by_feature["f3"]["sampleSizeValue"] == "10"
    assert check_zero_counts(table_of(rows), emit_absences=False).findings == []


def _derive(rows, excluded=(), confirmed_rows=None, **options):
    kept = table_of(rows)
    excluded_table = table_of(list(excluded), "excluded", kept.con)
    derivation = derive_fields.Derivation(excluded=excluded_table, **options)
    confirmed = None if confirmed_rows is None else table_of(confirmed_rows, "confirmed", kept.con)
    derived = derive_fields.derive(kept, derivation, confirmed)
    return derived, dicts(derived.table)


def _codes(result):
    return [f.code for f in result.findings.findings]


def test_derive_writes_occurrence_status_quantity_and_country_code():
    _, rows = _derive([{"sampleID": "S1", "featureID": "f1", "count": "10", **POINT_REYES}])

    assert rows[0]["occurrenceStatus"] == "present"
    assert rows[0]["countryCode"] == "US"
    assert rows[0]["organismQuantity"] == "10"


def test_derive_takes_a_confirmed_value_over_the_derived_one():
    confirmed = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "10",
            "organismQuantity": "12",
            "provenance": "the lab notebook",
        }
    ]

    result, rows = _derive(
        [
            {"sampleID": "S1", "featureID": "f1", "count": "10"},
            {"sampleID": "S2", "featureID": "f1", "count": "7"},
        ],
        confirmed_rows=confirmed,
    )

    assert {row["sampleID"]: row["organismQuantity"] for row in rows} == {"S1": "12", "S2": "7"}
    assert any(
        f.code == "DERIVED_VALUE_REPLACED" and "organismQuantity" in f.message
        for f in result.findings.findings
    )
    proposed = {row["sampleID"]: row for row in dicts(result.proposal)}
    assert proposed["S1"]["organismQuantity"] == "10"


def _confirm(
    row: dict[str, str], provenance: str = "the field sheet", confirmed: str = "PI", **changes: str
) -> dict:
    return {**row, **changes, "provenance": provenance, "confirmed": confirmed}


def test_a_proposed_row_has_empty_provenance_and_confirmed_columns():
    result, _ = _derive([{"sampleID": "S1", "featureID": "f1", "count": "10"}])
    row = dicts(result.proposal)[0]
    assert (row["provenance"], row["confirmed"]) == ("", "")


def test_a_confirmed_coordinate_moves_the_footprint_and_country_derived_from_it():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10", **POINT_REYES}]
    proposed, _ = _derive(rows)
    windsor = {"decimalLatitude": "42.30", "decimalLongitude": "-83.03"}
    _, published = _derive(rows, confirmed_rows=[_confirm(dicts(proposed.proposal)[0], **windsor)])
    assert published[0]["countryCode"] == "CA"
    assert published[0]["footprintWKT"] == "POINT (-83.03 42.3)"


def test_a_confirmed_count_changes_its_library_total():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "10"},
        {"sampleID": "S1", "featureID": "f2", "count": "5"},
    ]
    proposed, _ = _derive(rows)
    _, published = _derive(
        rows, confirmed_rows=[_confirm(dicts(proposed.proposal)[0], count="12")]
    )
    assert {row["sampleSizeValue"] for row in published} == {"17"}


def test_a_confirmed_derived_value_wins_over_the_value_derived_again():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10", **POINT_REYES}]
    proposed, _ = _derive(rows)
    confirmed = _confirm(dicts(proposed.proposal)[0], count="12", countryCode="MX")
    _, published = _derive(rows, confirmed_rows=[confirmed])
    assert published[0]["countryCode"] == "MX"
    assert published[0]["organismQuantity"] == "12"


def test_a_row_for_a_later_sample_changes_only_the_cells_it_fills():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10", **POINT_REYES}]
    proposed, _ = _derive(rows)
    later = {column: "" for column in dicts(proposed.proposal)[0]}
    later.update(sampleID="S1", featureID="f1", count="12", provenance="the field sheet")
    _, published = _derive(rows, confirmed_rows=[later])
    assert published[0]["organismQuantity"] == "12"
    assert published[0]["countryCode"] == "US"


def test_a_changed_row_without_provenance_refuses_the_sheet():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10"}]
    proposed, _ = _derive(rows)
    with pytest.raises(SheetRefused, match="S1"):
        _derive(rows, confirmed_rows=[_confirm(dicts(proposed.proposal)[0], "", count="12")])


def test_an_unchanged_row_needs_no_provenance():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10"}]
    proposed, _ = _derive(rows)
    result, _ = _derive(rows, confirmed_rows=[dicts(proposed.proposal)[0]])
    assert _codes(result) == _codes(proposed)


def test_a_changed_row_nobody_confirmed_is_applied_and_named_for_review():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10"}]
    proposed, _ = _derive(rows)
    confirmed = _confirm(dicts(proposed.proposal)[0], "read from the methods", "", count="12")
    result, published = _derive(rows, confirmed_rows=[confirmed])
    assert published[0]["organismQuantity"] == "12"
    assert result.rows == RowsChanged(changed=1, unconfirmed=1, first_unconfirmed=["S1/f1"])


def test_derive_proposes_the_rows_of_the_first_samples_only():
    rows = [
        {"sampleID": f"S{n:02}", "featureID": "f1", "count": "1"}
        for n in range(derive_fields.PROPOSED_SAMPLES + 5)
    ]

    result, _ = _derive(rows)

    assert (
        len({row["sampleID"] for row in dicts(result.proposal)}) == derive_fields.PROPOSED_SAMPLES
    )


def test_derive_reports_reads_left_out_of_the_published_totals():
    kept = [{"sampleID": "S1", "featureID": "f1", "count": "10"}]
    excluded = [{"sampleID": "S1", "featureID": "f2", "count": "5", "exclusion_reason": "human"}]

    result, rows = _derive(kept, excluded)

    assert "SAMPLE_SIZE_AFTER_EXCLUSIONS" in _codes(result)
    assert rows[0]["sampleSizeValue"] == "10"


def test_reads_left_out_are_counted_per_library_the_archive_publishes():
    kept = [
        {"sampleID": "S1", "marker": "12S", "featureID": "f1", "count": "10"},
        {"sampleID": "S1", "marker": "COI", "featureID": "f1", "count": "4"},
        {"sampleID": "S2", "marker": "12S", "featureID": "f1", "count": "7"},
    ]
    excluded = [
        {"sampleID": "S1", "marker": "12S", "featureID": "f2", "count": "5"},
        {"sampleID": "S1", "marker": "COI", "featureID": "f2", "count": "0"},
        {"sampleID": "NC1", "marker": "12S", "featureID": "f1", "count": "9"},
    ]

    log = _reads_left_out(kept, excluded)

    [finding] = log.findings
    assert finding.code == "SAMPLE_SIZE_AFTER_EXCLUSIONS"
    assert finding.count == 1
    assert "15" in finding.message
    assert "10" in finding.message


def test_no_reads_left_out_reports_nothing():
    kept = [{"sampleID": "S1", "featureID": "f1", "count": "10"}]
    assert _reads_left_out(kept, []).findings == []


def _reads_left_out(kept, excluded):
    kept_table = table_of(kept)
    excluded_table = table_of(excluded, "excluded", kept_table.con)
    return report_reads_excluded_from_totals(kept_table, excluded_table, {})


def test_derive_publishes_a_zero_count_as_absent():
    _, rows = _derive(
        [
            {"sampleID": "S1", "featureID": "f1", "count": "4"},
            {"sampleID": "S1", "featureID": "f2", "count": "0"},
        ]
    )
    by_feature = {row["featureID"]: row for row in rows}
    assert by_feature["f2"]["occurrenceStatus"] == "absent"
    assert by_feature["f2"]["organismQuantity"] == "0"
    assert not by_feature["f2"].get("dataGeneralizations")
    assert by_feature["f1"]["occurrenceStatus"] == "present"


@pytest.mark.parametrize(
    ("place", "given", "codes"),
    [
        (WINDSOR, "us", ["COUNTRY_CODE_CONTRADICTS_COORDINATES"]),
        (POINT_REYES, "us", []),
        (POINT_REYES, "Canada", []),
        (POINT_REYES, "CA", ["COUNTRY_CODE_CONTRADICTS_COORDINATES"]),
        (NEARSHORE, "MX", []),
        (OFFSHORE, "KI", []),
    ],
)
def test_a_given_country_code_is_kept_and_only_a_contradiction_reported(place, given, codes):
    result = _placed([{**place, "countryCode": given}])
    assert result.rows[0]["countryCode"] == given
    assert [f.code for f in result.findings.findings] == codes


@pytest.mark.parametrize(
    "confirmed",
    [[], [{"sampleID": "S1", "featureID": "f1", "provenance": "notes", "confirmed": "PI"}]],
    ids=["no rows", "no value columns"],
)
def test_a_sheet_that_names_no_value_changes_nothing(confirmed):
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10"}]
    result, published = _derive(rows, confirmed_rows=confirmed)
    assert published[0]["organismQuantity"] == "10"
    assert result.rows == RowsChanged()


def test_a_header_only_sheet_names_no_column_to_refuse():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10"}]
    kept = table_of(rows)
    sheet = kept.view("header_only", "SELECT 'x' AS gone, 'S1' AS sampleID WHERE FALSE")
    derivation = derive_fields.Derivation(excluded=table_of([], "excluded", kept.con))
    derived = derive_fields.derive(kept, derivation, sheet)
    assert derived.rows == RowsChanged()


def test_provenance_of_only_spaces_refuses_the_sheet():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10"}]
    proposed, _ = _derive(rows)
    with pytest.raises(SheetRefused, match="S1"):
        _derive(rows, confirmed_rows=[_confirm(dicts(proposed.proposal)[0], "  ", count="12")])


def test_confirmed_of_only_spaces_counts_as_unconfirmed():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10"}]
    proposed, _ = _derive(rows)
    confirmed = _confirm(dicts(proposed.proposal)[0], "notes", " ", count="12")
    result, _ = _derive(rows, confirmed_rows=[confirmed])
    assert result.rows == RowsChanged(changed=1, unconfirmed=1, first_unconfirmed=["S1/f1"])


def test_a_confirmed_row_leaves_no_unconfirmed_rows_to_name():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "10"}]
    proposed, _ = _derive(rows)
    result, _ = _derive(rows, confirmed_rows=[_confirm(dicts(proposed.proposal)[0], count="12")])
    assert result.rows == RowsChanged(changed=1, unconfirmed=0, first_unconfirmed=[])
