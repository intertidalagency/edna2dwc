from datetime import date, datetime
from functools import partial

import pytest

from edna2dwc.terms import formats


@pytest.mark.parametrize(
    "value",
    [
        "2021",
        "2021-03",
        "2021-03-04",
        "2021-03-04T15:30",
        "2021-03-04T15:30:00",
        "2021-03-04T15:30:00.25",
        "2021-03-04T15:30:00Z",
        "2021-03-04T15:30-0600",
        "2021-03-04T15:30:00+05:30",
        "2021-03-04/2021-03-10",
    ],
)
def test_validate_iso8601_date_accepts_every_documented_shape(value):
    assert formats.validate_iso8601_date(value)


@pytest.mark.parametrize(
    ("value", "converted"),
    [
        ("2014-02-20T15:33", "2014-02-20T15:33"),
        ("2014-2-20T9:05:07", "2014-02-20T09:05:07"),
        ("2014-02-20T15:33:00-08:00", "2014-02-20T15:33:00-08:00"),
        ("2014-02-20T15:33:00Z", "2014-02-20T15:33:00Z"),
    ],
)
def test_convert_iso8601_date_keeps_the_time_zone_the_source_gave(value, converted):
    assert formats.convert_iso8601_date(value) == converted


@pytest.mark.parametrize(
    ("value", "converted"),
    [
        ("2025-06-04 23:30", "2025-06-04T23:30"),
        ("2025-6-4 9:05:07Z", "2025-06-04T09:05:07Z"),
    ],
)
def test_convert_iso8601_date_accepts_a_space_between_date_and_time(value, converted):
    assert formats.convert_iso8601_date(value) == converted


_ISO_CODES = frozenset({"US", "CA", "FR"})
LATITUDE = partial(formats.validate_decimal_degrees, max_abs=90)
LONGITUDE = partial(formats.validate_decimal_degrees, max_abs=180)
ALPHA2 = partial(formats.validate_iso3166_alpha2, valid_codes=_ISO_CODES)
OCCURRENCE_STATUS = partial(
    formats.validate_controlled, vocabulary=formats.OCCURRENCE_STATUS_VOCABULARY
)
ANY_VOCABULARY = partial(formats.validate_controlled, vocabulary=None)


@pytest.mark.parametrize(
    ("validate", "value", "valid"),
    [
        (formats.validate_iso8601_date, "03/04/2021", False),
        (LATITUDE, "3641.20", False),
        (LATITUDE, "-41.0983423", True),
        (LATITUDE, "91.0", False),
        (LONGITUDE, "70 6 N", False),
        (LONGITUDE, "70.1W", False),
        (ALPHA2, "USA", False),
        (ALPHA2, "US", True),
        (OCCURRENCE_STATUS, "present", True),
        (OCCURRENCE_STATUS, "PRESENT", False),
        (ANY_VOCABULARY, "anything", True),
        (ANY_VOCABULARY, "", False),
        (formats.validate_nonneg_number, "0", True),
        (formats.validate_nonneg_number, "12.5", True),
        (formats.validate_nonneg_number, "-5", False),
        (formats.validate_nonneg_number, "5 m", False),
        (formats.validate_number_with_unit, "60 C", False),
        (formats.validate_number_with_unit, "60", True),
        (formats.validate_uri, "urn:lsid:marinespecies.org:taxname:126436", True),
        (formats.validate_uri, "https://www.gbif.org/species/1234", True),
        (formats.validate_uri, "NCBI:txid9606", True),
        (formats.validate_uri, "NCBI:txidNCBI:txid1", False),
        (formats.validate_uri, "NCBI:txid", False),
        (formats.validate_uri, "NCBI:9606", False),
        (formats.validate_uri, "NCBI:txid09606", False),
        (formats.validate_uri, "ncbi:txid9606x", False),
        (formats.validate_uri, "not a uri", False),
        (formats.validate_wkt, "POINT (-70.1 41.2)", True),
        (formats.validate_wkt, "LINESTRING (-70.1 41.2, -70.2 41.3)", True),
        (formats.validate_wkt, "41.2, -70.1", False),
        (formats.validate_dna_sequence, "ACGTN", True),
        (formats.validate_dna_sequence, "acgt", False),
        (formats.validate_dna_sequence, "ACG-T", False),
        (formats.validate_dna_sequence, "ACGU", False),
        (formats.validate_dna_sequence, "NNNN", False),
        (formats.validate_pipe_list, "a | b | c", True),
        (formats.validate_pipe_list, "a | b | ", False),
    ],
)
def test_a_validator_accepts_only_a_well_formed_value(validate, value, valid):
    assert bool(validate(value)) is valid


@pytest.mark.parametrize(
    ("convert", "value", "converted"),
    [
        (formats.convert_iso8601_date, "03/04/2021", None),
        (formats.convert_iso8601_date, "2021-03-04", "2021-03-04"),
        (formats.convert_iso8601_date, "2021-9-5 / 2021-9-6", "2021-09-05/2021-09-06"),
        (formats.convert_iso8601_date, "2021-9-5/2021-9-6", "2021-09-05/2021-09-06"),
        (partial(formats.convert_decimal_degrees, max_abs=90.0), "3641.20", None),
        (partial(formats.convert_iso3166_alpha2, valid_codes=_ISO_CODES), "USA", None),
        (partial(formats.convert_iso3166_alpha2, valid_codes=_ISO_CODES), "us", "US"),
        (
            partial(formats.convert_controlled, vocabulary=formats.BASIS_OF_RECORD_VOCABULARY),
            "MATERIALSAMPLE",
            "MaterialSample",
        ),
        (
            partial(formats.convert_controlled, vocabulary=formats.BASIS_OF_RECORD_VOCABULARY),
            "SomeRandomThing",
            None,
        ),
        (formats.convert_dna_sequence, "acgt", "ACGT"),
        (formats.convert_pipe_list, "a|b |  c", "a | b | c"),
    ],
)
def test_a_converter_normalizes_a_value_and_never_guesses(convert, value, converted):
    assert convert(value) == converted


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ACG T\nACG", "ACGTACG"),
        ("ACG--T..A", "ACGTA"),
        ("acgu", "ACGT"),
    ],
)
def test_convert_dna_sequence_drops_whitespace_and_gaps_and_reads_rna_as_dna(value, expected):
    assert formats.convert_dna_sequence(value) == expected


@pytest.mark.parametrize("value", ["NNNN", "----", "ACGTXZ", "ACGT*"])
def test_convert_dna_sequence_refuses_a_value_that_is_not_a_sequence(value):
    assert formats.convert_dna_sequence(value) is None


def test_ddmm_to_decimal_converts_degrees_and_minutes():
    assert formats.ddmm_to_decimal(3641.20) == pytest.approx(36 + 41.20 / 60)


def test_ddmm_to_decimal_handles_the_sign_trap_for_southern_western_coordinates():
    positive = formats.ddmm_to_decimal(3641.20)
    negative = formats.ddmm_to_decimal(-3641.20)
    assert negative == pytest.approx(-positive)


def test_excel_serial_to_iso_date_1900_epoch():
    assert formats.excel_serial_to_iso_date(1, epoch="1900") == "1900-01-01"


def test_excel_serial_to_iso_date_1900_epoch_around_the_phantom_leap_day():
    assert formats.excel_serial_to_iso_date(59, epoch="1900") == "1900-02-28"
    assert formats.excel_serial_to_iso_date(60, epoch="1900") == "1900-02-28"
    assert formats.excel_serial_to_iso_date(61, epoch="1900") == "1900-03-01"


def test_excel_serial_to_iso_date_1904_epoch():
    assert formats.excel_serial_to_iso_date(0, epoch="1904") == "1904-01-01"


def test_excel_serial_to_iso_date_rejects_an_unrecognized_epoch():
    with pytest.raises(ValueError):
        formats.excel_serial_to_iso_date(1, epoch="1985")


def test_utc_from_local_converts_local_time_to_utc_by_coordinate():
    result = formats.utc_from_local("2021-03-04T12:00:00", lat=41.2, lon=-70.1)
    assert result == "2021-03-04T17:00:00Z"


def test_utc_from_local_leaves_a_date_without_a_time_as_a_date():
    assert formats.utc_from_local("2021-03-04", lat=-33.9, lon=151.2) == "2021-03-04"


def test_utc_from_local_honours_a_stated_offset():
    result = formats.utc_from_local("2021-03-04T10:00+02:00", lat=41.2, lon=-70.1)
    assert result == "2021-03-04T08:00:00Z"


@pytest.mark.parametrize(
    ("cell", "converted"),
    [
        (date(2021, 3, 4), "2021-03-04"),
        (datetime(2021, 3, 4), "2021-03-04"),
        (datetime(2021, 3, 4, 12, 0), "2021-03-04T17:00:00Z"),
    ],
)
def test_utc_from_local_takes_a_spreadsheet_date_or_datetime_cell(cell, converted):
    assert formats.utc_from_local(cell, lat=41.2, lon=-70.1) == converted


def test_nad83_to_wgs84_reprojects_within_a_fraction_of_a_degree():
    lat, lon = formats.nad83_to_wgs84(41.2, -70.1)
    assert abs(lat - 41.2) < 0.01
    assert abs(lon - (-70.1)) < 0.01


def test_every_single_value_transform_takes_exactly_one_argument():
    for name, func in formats.SINGLE_VALUE_TRANSFORMS.items():
        value = 4530.5 if name in ("ddmm", "excel_date") else "2021-03-04"
        assert func(value) is not None, name


def test_converters_emit_values_their_own_validators_accept():
    converted = formats.convert_iso8601_date("2021-03-04")
    assert converted is not None and formats.validate_iso8601_date(converted)

    converted = formats.convert_decimal_degrees(" -41.0983423 ", max_abs=90.0)
    assert converted is not None and formats.validate_decimal_degrees(converted, max_abs=90.0)

    converted = formats.convert_iso3166_alpha2("us", valid_codes=_ISO_CODES)
    assert converted is not None and formats.validate_iso3166_alpha2(
        converted, valid_codes=_ISO_CODES
    )

    converted = formats.convert_controlled(
        "materialsample", vocabulary=formats.BASIS_OF_RECORD_VOCABULARY
    )
    assert converted is not None and formats.validate_controlled(
        converted, vocabulary=formats.BASIS_OF_RECORD_VOCABULARY
    )

    converted = formats.convert_nonneg_number(" 12.5 ")
    assert converted is not None and formats.validate_nonneg_number(converted)

    converted = formats.convert_uri(" urn:lsid:marinespecies.org:taxname:126436 ")
    assert converted is not None and formats.validate_uri(converted)

    converted = formats.convert_wkt(" POINT (-70.1 41.2) ")
    assert converted is not None and formats.validate_wkt(converted)

    converted = formats.convert_dna_sequence("acgtn")
    assert converted is not None and formats.validate_dna_sequence(converted)

    converted = formats.convert_pipe_list("a|b |  c")
    assert converted is not None and formats.validate_pipe_list(converted)
