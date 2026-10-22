import re

import pytest

from edna2dwc.common.findings import (
    CODES,
    ERROR,
    VARIABLE_SEVERITY_CODES,
    WARNING,
    FindingsLog,
    new_finding,
)
from tests.paths import PACKAGE_DIR


def test_every_code_has_a_place_in_the_package_that_raises_it():
    readers_of_codes = {PACKAGE_DIR / "findings.py", PACKAGE_DIR / "review" / "report.py"}
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in PACKAGE_DIR.rglob("*.py")
        if path not in readers_of_codes
    )
    unraised = sorted(code for code in CODES if not re.search(rf"\b{code}\b", sources))
    assert unraised == [], f"codes nothing raises; add the producer or delete the code: {unraised}"


def test_new_finding_rejects_a_code_outside_the_vocabulary():
    with pytest.raises(ValueError, match="NOT_A_REAL_CODE"):
        new_finding("NOT_A_REAL_CODE", "whatever")


def test_new_finding_applies_the_default_severity():
    finding = new_finding("TAXON_UNRESOLVED", "no register match")
    assert finding.severity == WARNING


def test_new_finding_requires_explicit_severity_for_variable_severity_codes():
    for code in VARIABLE_SEVERITY_CODES:
        with pytest.raises(ValueError, match=code):
            new_finding(code, "whatever")
        finding = new_finding(code, "whatever", severity=ERROR)
        assert finding.severity == ERROR


def test_new_finding_rejects_an_invalid_severity():
    with pytest.raises(ValueError, match="'critical'"):
        new_finding("TAXON_UNRESOLVED", "whatever", severity="critical")


def test_finding_to_dict_matches_the_reported_json_shape():
    finding = new_finding(
        "TAXON_UNRESOLVED", "1124 names", count=1124, detail_file="unresolved.tsv"
    )
    assert finding.to_dict() == {
        "severity": "warning",
        "code": "TAXON_UNRESOLVED",
        "message": "1124 names",
        "count": 1124,
        "detail_file": "unresolved.tsv",
    }


def test_finding_to_dict_omits_detail_file_when_absent():
    finding = new_finding("TERM_UNMAPPED", "column x")
    assert "detail_file" not in finding.to_dict()


def test_findings_log_accumulates_and_serializes():
    log = FindingsLog()
    log.add("TERM_UNMAPPED", "column x")
    log.add("TAXON_UNRESOLVED", "1124 names", count=1124)

    assert len(log.findings) == 2
    assert log.to_list() == [f.to_dict() for f in log.findings]


def test_findings_log_has_errors():
    log = FindingsLog()
    assert log.has_errors() is False

    log.add("TERM_UNMAPPED", "warning only")
    assert log.has_errors() is False

    log.add("CONTRACT_INVALID", "a real problem")
    assert log.has_errors() is True
