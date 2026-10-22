import pytest



@pytest.mark.parametrize(
    "value",
)
def test_validate_iso8601_date_accepts_every_documented_shape(value):
    assert formats.validate_iso8601_date(value)


_ISO_CODES = frozenset({"US", "CA", "FR"})


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
        formats.excel_serial_to_iso_date(1, epoch="1985")


def test_utc_from_local_converts_local_time_to_utc_by_coordinate():
    result = formats.utc_from_local("2021-03-04T12:00:00", lat=41.2, lon=-70.1)
    assert result == "2021-03-04T17:00:00Z"


def test_nad83_to_wgs84_reprojects_within_a_fraction_of_a_degree():
    lat, lon = formats.nad83_to_wgs84(41.2, -70.1)
    assert abs(lat - 41.2) < 0.01
    assert abs(lon - (-70.1)) < 0.01


def test_converters_emit_values_their_own_validators_accept():
    converted = formats.convert_iso8601_date("2021-03-04")

    converted = formats.convert_decimal_degrees(" -41.0983423 ", max_abs=90.0)

    converted = formats.convert_iso3166_alpha2("us", valid_codes=_ISO_CODES)

    converted = formats.convert_controlled(
        "materialsample", vocabulary=formats.BASIS_OF_RECORD_VOCABULARY
    )

    converted = formats.convert_nonneg_number(" 12.5 ")

    converted = formats.convert_uri(" urn:lsid:marinespecies.org:taxname:126436 ")

    converted = formats.convert_wkt(" POINT (-70.1 41.2) ")

    converted = formats.convert_dna_sequence("acgtn")

    converted = formats.convert_pipe_list("a|b |  c")
