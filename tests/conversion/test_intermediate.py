import pytest

from tests.make_fixtures import FIXTURES, FIXTURES_DIR


def codes(log):
    return [f.code for f in log.findings]


@pytest.mark.parametrize(("filename", "expected_codes"), [(f, c) for f, _content, c in FIXTURES])
def test_fixture_produces_its_designated_codes(filename, expected_codes):
    path = FIXTURES_DIR / filename
    log = validate_intermediate(path)
    if not expected_codes:
        assert log.findings == [], f"{filename} should be valid, got {codes(log)}"
    else:
        for code in expected_codes:
            assert code in codes(log), f"{filename} should produce {code}, got {codes(log)}"


def test_multiple_violations_all_accumulate_not_just_the_first(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text("sampleID\tfeatureID\tcount\ttaxonomy\ns1\t\tNA\td__Bacteria\n")
    log = validate_intermediate(path)
    assert len(log.findings) >= 2
