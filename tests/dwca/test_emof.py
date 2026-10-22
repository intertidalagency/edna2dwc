from dataclasses import dataclass
import json

import pytest

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import ROW, column
from edna2dwc.dwca import emof
from edna2dwc.terms.dynamic_properties import DynamicProperties
from tests.tables import dicts, table_of

TEMPERATURE_URI = "http://vocab.nerc.ac.uk/collection/P01/current/TEMPPR01/"
SALINITY_URI = "http://vocab.nerc.ac.uk/collection/P01/current/PSALPR01/"
CELSIUS_URI = "http://vocab.nerc.ac.uk/collection/P06/current/UPAA/"
PSU_URI = "http://vocab.nerc.ac.uk/collection/P06/current/UUUU/"


@dataclass
class _Built:
    core_rows: list[dict[str, str]]
    emof_rows: list[dict[str, str]]
    findings: FindingsLog


def _entries(table) -> emof.DynamicEntries:
    return emof.dynamic_entries(table, DynamicProperties.published_in(table))


def _measurement_keys(rows):
    return _entries(table_of(rows)).keys_that_look_measured()


def _emof(rows, units=None, measured=None) -> _Built:
    core = table_of(rows)
    entries = _entries(core)
    selected = entries.measurement_keys(
        entries.keys_that_look_measured() if measured is None else measured
    )
    built, findings = emof.build_emof(entries.table, selected, units=units)
    published = DynamicProperties.published_in(core).folded(core, removed=selected)
    columns = ", ".join(column(name) for name in emof.EMOF_HEADER)
    emof_rows = [
        dict(zip(emof.EMOF_HEADER, values, strict=True))
        for values in built.rows(
            f"SELECT {columns} FROM {built.name} ORDER BY {ROW}, {emof.INDEX}"
        )
    ]
    return _Built(
        dicts(published), emof_rows, FindingsLog(entries.malformed.findings + findings.findings)
    )


def _numeric(values):
    return "reading" in emof.measurement_columns(
        table_of([{"reading": v} for v in values]), ["reading"]
    )


@pytest.mark.parametrize(
    ("header", "split"),
    [("temp_C", ("temp", "C")), ("depth (m)", ("depth", "m")), ("salinity", ("salinity", None))],
)
def test_split_header_unit_splits_off_a_trailing_unit(header, split):
    assert emof.split_header_unit(header) == split


@pytest.mark.parametrize(
    ("header", "expected_type"),
    [
        ("Temp_C", "temperature"),
        ("dissolved_oxygen", "dissolved oxygen"),
        ("Dissolved_Oxygen", "dissolved oxygen"),
        ("tow_duration", "tow duration"),
    ],
)
def test_alias_for_matches_a_known_header_case_insensitively_and_whole(header, expected_type):
    alias = emof.alias_for(header)
    assert alias is not None
    assert alias.measurement_type == expected_type


@pytest.mark.parametrize(
    "header",
    [
        "station_notes",
        "temp_station",
        "nitrate_nitrite",
        "pCO2_corrected",
        "pH_total",
        "temp (surface)",
    ],
)
def test_alias_for_matches_no_unrecognized_header_or_suffix_that_is_not_a_unit(header):
    assert emof.alias_for(header) is None


def test_columns_that_share_a_base_but_not_a_unit_publish_distinct_measurement_types():
    rows = [
        {
            "occurrenceID": "occ1",
            "dynamicProperties": json.dumps(
                {"pCO2_corrected": "400", "pCO2_uncorrected": "410", "pCO2_uatm": "405"}
            ),
        }
    ]
    types = [row["measurementType"] for row in _emof(rows).emof_rows]
    assert types == ["pCO2_corrected", "pCO2_uncorrected", "pCO2"]


@pytest.mark.parametrize(
    ("values", "numeric"),
    [
        (["1"] * 19 + ["x"], True),
        (["1"] * 18 + ["x", "y"], False),
        (["23.5 C", "24.1C", "22.0"], True),
        (["12.5 ug/L", "13.0 ug/L", "11.8 ug/L"], True),
        (["3.5 µg/L", "4.1 µg/L"], True),
        (["400 uatm", "410 uatm"], True),
        (["12.3 F", "5 m", "30s", "2 L"], True),
        (["16S", "18S", "12S"], False),
        (["5M", "6M"], False),
        (["12 knots", "3 knots"], False),
        (["1", "2", "", ""], True),
        (["", ""], False),
        (["1", "NA", "n/a", "NaN", "null"], True),
    ],
)
def test_a_column_is_a_measurement_when_nearly_all_its_values_are_numbers_with_known_units(
    values, numeric
):
    assert _numeric(values) is numeric


def test_a_value_that_says_no_value_publishes_no_measurement_row():
    rows = [
        {"occurrenceID": "occ1", "dynamicProperties": json.dumps({"temp_C": "12.5"})},
        {"occurrenceID": "occ2", "dynamicProperties": json.dumps({"temp_C": "NA"})},
    ]
    result = _emof(rows)
    assert [r["measurementValue"] for r in result.emof_rows] == ["12.5"]


def test_a_blank_dynamic_properties_cell_has_no_properties_and_stays_blank():
    built = _emof([{"occurrenceID": "occ1", "dynamicProperties": ""}])
    assert built.emof_rows == []
    assert built.findings.findings == []
    assert "dynamicProperties" not in built.core_rows[0]


@pytest.mark.parametrize("raw", ["{not json", "[1, 2, 3]"])
def test_a_value_that_is_not_a_json_object_is_disclosed_and_ignored(raw):
    built = _emof([{"occurrenceID": "occ1", "dynamicProperties": raw}])
    assert [f.code for f in built.findings.findings] == ["DYNAMIC_PROPERTIES_MALFORMED"]
    assert "dynamicProperties" not in built.core_rows[0]


def test_a_numeric_column_becomes_measurement_rows_and_leaves_the_rest_in_place():
    rows = [
        {
            "occurrenceID": "occ1",
            "dynamicProperties": json.dumps({"temp_C": "12.5", "notes": "clear day"}),
        },
        {
            "occurrenceID": "occ2",
            "dynamicProperties": json.dumps({"temp_C": "13.0", "notes": "cloudy"}),
        },
    ]
    assert _measurement_keys(rows) == ["temp_C"]
    result = _emof(rows)
    assert [(r["measurementType"], r["measurementValue"]) for r in result.emof_rows] == [
        ("temperature", "12.5"),
        ("temperature", "13.0"),
    ]
    assert [json.loads(r["dynamicProperties"]) for r in result.core_rows] == [
        {"notes": "clear day"},
        {"notes": "cloudy"},
    ]


def test_given_the_measured_keys_only_they_become_measurement_rows():
    properties = {"temp_C": "12.5", "latitude": "47.6", "size_upper": ">0.8"}
    rows = [{"occurrenceID": "occ1", "dynamicProperties": json.dumps(properties)}]
    entries = _entries(table_of(rows))
    assert list(entries.measurement_keys({"size_upper"})) == ["size_upper"]


@pytest.mark.parametrize("name", ["marker", "sequence", "taxonomy", "kingdom", "notes"])
def test_a_reserved_or_text_column_is_never_selected_as_a_measurement(name):
    rows = [{"occurrenceID": "occ1", "dynamicProperties": json.dumps({name: "16S"})}]
    assert _measurement_keys(rows) == []


@pytest.mark.parametrize(
    ("header", "value", "published"),
    [
        ("salinity", "12.5", ("salinity", "12.5", "", SALINITY_URI, "")),
        ("salinity_psu", "12.5", ("salinity", "12.5", "PSU", SALINITY_URI, PSU_URI)),
        ("temp_F", "12.5", ("temperature", "12.5", "degrees Fahrenheit", TEMPERATURE_URI, "")),
        (
            "temp_C",
            "12.5",
            ("temperature", "12.5", "degrees Celsius", TEMPERATURE_URI, CELSIUS_URI),
        ),
        ("bottom depth (fathoms)", "12.5", ("bottom depth (fathoms)", "12.5", "fathoms", "", "")),
        ("temperature (surface)", "12.5", ("temperature (surface)", "12.5", "", "", "")),
        ("bottom_depth", "12.5", ("bottom_depth", "12.5", "", "", "")),
        ("temp_min", "12.5", ("temp_min", "12.5", "", "", "")),
        ("tow_duration_minutes", "12.5", ("tow duration", "12.5", "min", "", "")),
        ("nitrate_umol", "12.5", ("nitrate", "12.5", "umol", "", "")),
        ("nitrate_umol/L", "12.5", ("nitrate", "12.5", "umol/L", "", "")),
        (
            "temperature",
            "12.3 F",
            ("temperature", "12.3", "degrees Fahrenheit", TEMPERATURE_URI, ""),
        ),
        ("temperature", "12.3 xyz", ("temperature", "12.3 xyz", "", TEMPERATURE_URI, "")),
        (
            "temp_C",
            "12.3 C",
            ("temperature", "12.3", "degrees Celsius", TEMPERATURE_URI, CELSIUS_URI),
        ),
        ("reading", "30 s", ("reading", "30", "s", "", "")),
        ("reading", "12m", ("reading", "12", "m", "", "")),
        ("reading", "1 L", ("reading", "1", "L", "", "")),
        ("reading", "4C", ("reading", "4", "degrees Celsius", "", CELSIUS_URI)),
    ],
)
def test_a_measurement_takes_its_type_from_the_header_and_its_unit_from_the_header_or_value(
    header, value, published
):
    rows = [{"occurrenceID": "occ1", "dynamicProperties": json.dumps({header: value})}]
    (row,) = _emof(rows).emof_rows
    assert published == (
        row["measurementType"],
        row["measurementValue"],
        row["measurementUnit"],
        row["measurementTypeID"],
        row["measurementUnitID"],
    )


@pytest.mark.parametrize("value", ["16S", "18S", "12S", "28S", "5M"])
def test_a_single_letter_in_a_value_is_a_unit_only_in_its_symbols_case(value):
    rows = [{"occurrenceID": "occ1", "dynamicProperties": json.dumps({"gene": value})}]
    (row,) = _emof(rows, measured={"gene"}).emof_rows
    assert row["measurementValue"] == value
    assert row["measurementUnit"] == ""


def test_a_numeric_column_with_no_vocabulary_or_unit_is_reported_once_with_a_count():
    rows = [
        {"occurrenceID": f"occ{n}", "dynamicProperties": json.dumps({"custom_reading": "42"})}
        for n in range(3)
    ]
    result = _emof(rows)
    assert {(r["measurementType"], r["measurementTypeID"]) for r in result.emof_rows} == {
        ("custom_reading", "")
    }
    unvocabularied, incomplete = result.findings.findings
    assert (unvocabularied.code, unvocabularied.count) == ("EMOF_TYPE_UNVOCABULARIED", 3)
    assert (incomplete.code, incomplete.count) == ("TERM_PAIR_INCOMPLETE", 3)
    assert "units.custom_reading" in incomplete.message
    assert "temp_C" in incomplete.message


def test_a_non_numeric_unmatched_column_stays_in_dynamic_properties():
    rows = [{"occurrenceID": "occ1", "dynamicProperties": json.dumps({"site_notes": "muddy"})}]
    result = _emof(rows)
    assert result.emof_rows == []
    assert json.loads(result.core_rows[0]["dynamicProperties"]) == {"site_notes": "muddy"}


def test_select_and_build_emof_handles_rows_with_no_dynamic_properties_at_all():
    rows = [{"occurrenceID": "occ1", "scientificName": "Mytilus californianus"}]
    result = _emof(rows)
    assert result.emof_rows == []
    assert "dynamicProperties" not in result.core_rows[0]


_METHODS = "document:methods.pdf"


def _with_units(header: str, values: list[str], unit: str) -> _Built:
    rows = [
        {"occurrenceID": f"occ{i}", "dynamicProperties": json.dumps({header: value})}
        for i, value in enumerate(values)
    ]
    return _emof(rows, units={header: (unit, _METHODS)})


def _build_with_units(header: str, value: str, unit: str) -> dict[str, str]:
    return _with_units(header, [value], unit).emof_rows[0]


def _overrides(built: _Built) -> list[str]:
    return [f.message for f in built.findings.findings if f.code == "MEASUREMENT_UNIT_OVERRIDDEN"]


@pytest.mark.parametrize(
    ("header", "value", "unit", "published"),
    [
        ("conductivity", "4.2", "mS/cm", ("4.2", "mS/cm", "")),
        ("salinity", "31", "psu", ("31", "PSU", PSU_URI)),
        ("temperature", "12.3 F", "degrees Celsius", ("12.3", "degrees Celsius", CELSIUS_URI)),
        ("temp_C", "54", "degrees Fahrenheit", ("54", "degrees Fahrenheit", "")),
    ],
)
def test_a_unit_from_answers_wins_over_the_header_and_values(header, value, unit, published):
    row = _build_with_units(header, value, unit)
    assert published == (row["measurementValue"], row["measurementUnit"], row["measurementUnitID"])


def test_a_unit_from_answers_keeps_a_value_whose_trailing_token_is_no_known_unit():
    rows = [{"occurrenceID": "occ1", "dynamicProperties": json.dumps({"wind": "12 knots"})}]
    (row,) = _emof(rows, units={"wind": ("m/s", _METHODS)}, measured=("wind",)).emof_rows
    assert (row["measurementValue"], row["measurementUnit"]) == ("12 knots", "m/s")


def test_a_unit_from_answers_that_replaces_an_inferred_one_is_reported_once():
    (message,) = _overrides(_with_units("temp_C", ["54", "55"], "degrees Fahrenheit"))
    assert "degrees Celsius (from the header)" in message
    assert "degrees Fahrenheit" in message
    assert _METHODS in message


def test_a_unit_from_answers_given_by_its_name_is_the_listed_unit():
    built = _with_units("temperature_C", ["12"], "Degrees Celsius")
    assert _overrides(built) == []
    assert built.emof_rows[0]["measurementUnitID"] == CELSIUS_URI


def test_a_unit_from_answers_that_agrees_or_fills_a_gap_is_not_reported():
    assert _overrides(_with_units("temp_C", ["12"], "celsius")) == []
    assert _overrides(_with_units("conductivity", ["4.2"], "mS/cm")) == []


def _mixed(built: _Built) -> list:
    return [f for f in built.findings.findings if f.code == "MEASUREMENT_UNITS_MIXED"]


def test_a_unit_from_answers_refuses_values_that_state_different_units():
    (finding,) = _mixed(_with_units("temperature", ["12 C", "54 F", "13 C"], "degrees Celsius"))
    assert finding.severity == "error"
    assert "degrees Celsius" in finding.message
    assert "degrees Fahrenheit" in finding.message
    assert "units.temperature" in finding.message


def test_a_unit_from_answers_accepts_values_that_state_one_unit_or_none():
    assert _mixed(_with_units("temperature", ["12.3 F", "13 F"], "degrees Celsius")) == []
    assert _mixed(_with_units("temperature", ["12 C", "13"], "degrees Celsius")) == []


def test_a_unit_from_answers_refuses_values_that_state_different_units_under_a_header_unit():
    (finding,) = _mixed(_with_units("temp_C", ["12 C", "54 F"], "degrees Celsius"))
    assert "degrees Fahrenheit" in finding.message


def test_a_unit_from_answers_that_agrees_with_the_header_refuses_a_value_stating_another():
    (finding,) = _mixed(_with_units("temp_C", ["12", "54 F"], "degrees Celsius"))
    assert "degrees Celsius" in finding.message
    assert "degrees Fahrenheit" in finding.message


def _temperatures(values: list[str]) -> _Built:
    return _emof(
        [
            {"occurrenceID": f"occ{i}", "dynamicProperties": json.dumps({"temperature_C": value})}
            for i, value in enumerate(values)
        ]
    )


def test_a_value_stating_a_unit_other_than_the_headers_is_refused_and_kept_as_written():
    built = _temperatures(["12", "54 F"])
    (finding,) = _mixed(built)
    assert finding.severity == "error"
    assert finding.message.startswith(
        "'temperature_C': the header names degrees Celsius, but the values state "
        "degrees Fahrenheit"
    )
    assert [row["measurementValue"] for row in built.emof_rows] == ["12", "54 F"]


def test_a_value_stating_the_headers_unit_publishes_its_number():
    built = _temperatures(["12 C", "13"])
    assert _mixed(built) == []
    assert [row["measurementValue"] for row in built.emof_rows] == ["12", "13"]


def _described(rows, units=None) -> dict[str, str]:
    table = table_of(rows)
    return emof.describe_measurements(
        table, emof.measurement_columns(table, list(rows[0])), units or {}
    )


def test_a_description_names_the_measurement_type_and_where_its_unit_came_from():
    described = _described(
        [{"temp_C": "12", "depth": "3 m", "conductivity": "4.2", "reading": "7"}],
        units={"conductivity": ("mS/cm", _METHODS)},
    )
    assert described == {
        "temp_C": "measurementType=temperature; measurementUnit=degrees Celsius (from the header)",
        "depth": "measurementType=depth; measurementUnit=m (from the values)",
        "conductivity": "measurementType=conductivity; measurementUnit=mS/cm (from units:)",
        "reading": "measurementType=reading; measurementUnit=none",
    }


def test_a_description_names_a_unit_from_answers_over_the_one_the_header_names():
    described = _described([{"temp_C": "54"}], units={"temp_C": ("degrees Fahrenheit", _METHODS)})
    assert described["temp_C"] == (
        "measurementType=temperature; measurementUnit=degrees Fahrenheit (from units:)"
    )


def test_a_description_skips_a_value_that_says_no_value():
    described = _described([{"depth": "3 m"}, {"depth": "NA"}])
    assert described["depth"] == "measurementType=depth; measurementUnit=m (from the values)"


def test_a_description_lists_each_unit_a_columns_values_give():
    described = _described([{"depth": "3 m"}, {"depth": "10 ft"}, {"depth": "4"}])
    assert described["depth"] == (
        "measurementType=depth; measurementUnit=m (from the values), ft (from the values), none"
    )
