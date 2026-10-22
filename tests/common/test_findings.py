import pytest

    CODES,
    ERROR,
    VARIABLE_SEVERITY_CODES,
    WARNING,
    FindingsLog,
    new_finding,
)


def test_new_finding_rejects_a_code_outside_the_vocabulary():
        new_finding("NOT_A_REAL_CODE", "whatever")


def test_new_finding_applies_the_default_severity():
    finding = new_finding("TAXON_UNRESOLVED", "no register match")
    assert finding.severity == WARNING


def test_new_finding_requires_explicit_severity_for_variable_severity_codes():
    for code in VARIABLE_SEVERITY_CODES:
            new_finding(code, "whatever")
        finding = new_finding(code, "whatever", severity=ERROR)
        assert finding.severity == ERROR


def test_new_finding_rejects_an_invalid_severity():
        new_finding("TAXON_UNRESOLVED", "whatever", severity="critical")


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
    assert "detail_file" not in finding.to_dict()


def test_findings_log_accumulates_and_serializes():
    log = FindingsLog()
    log.add("TAXON_UNRESOLVED", "1124 names", count=1124)

    assert len(log.findings) == 2
    assert log.to_list() == [f.to_dict() for f in log.findings]


def test_findings_log_has_errors():
    log = FindingsLog()
    assert log.has_errors() is False

    assert log.has_errors() is False

    log.add("CONTRACT_INVALID", "a real problem")
    assert log.has_errors() is True
