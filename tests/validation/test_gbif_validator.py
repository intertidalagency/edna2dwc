from __future__ import annotations

import zipfile

import httpx
import pytest

from edna2dwc.validation import gbif_validator as gv
from edna2dwc.validation.credentials import MISSING, Credentials, Unavailable

ACCOUNT = Credentials(username="u", password="p", source="a test")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def zip_path(tmp_path):
    path = tmp_path / "dwca.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("occurrence.txt", "occurrenceID\n")
    return path


def test_gbif_severity_for_matches_the_live_verified_mapping():
    assert gv.gbif_severity_for("ERROR") == "error"
    assert gv.gbif_severity_for("WARNING") == "warning"
    assert gv.gbif_severity_for("INFO") == "info"
    assert gv.gbif_severity_for("SOME_FUTURE_VALUE") == "info"


def test_parse_issues_extracts_category_and_count_from_the_real_response_shape():
    result = {
        "metrics": {
            "files": [
                {
                    "issues": [
                        {"issue": "RECORD_REFERENCES_TAXON_MATCH_NONE", "count": 5},
                        {"issue": "OCCURRENCE_ID_NOT_UNIQUE", "count": 2},
                    ]
                }
            ]
        }
    }
    issues = gv.parse_issues(result)
    assert issues == [
        gv.GbifIssue("RECORD_REFERENCES_TAXON_MATCH_NONE", "info", 5),
        gv.GbifIssue("OCCURRENCE_ID_NOT_UNIQUE", "info", 2),
    ]


def test_parse_issues_handles_a_present_but_null_metrics_or_issues():
    assert gv.parse_issues({"metrics": None}) == []
    assert gv.parse_issues({"metrics": {"files": [{"issues": None}]}}) == []


def test_run_gbif_validation_reports_unavailable_credentials_without_calling_gbif(zip_path):
    unavailable = Unavailable(MISSING, "no GBIF account is configured")
    log, issues = gv.run_gbif_validation(
        zip_path, credentials=unavailable, client=_client(_never_called)
    )
    assert [(f.code, f.message) for f in log.findings] == [(MISSING, unavailable.detail)]
    assert issues == []


def test_run_gbif_validation_separates_a_rejected_account_from_an_unreachable_api(zip_path):
    log, _ = gv.run_gbif_validation(
        zip_path,
        credentials=Credentials(username="u", password="hunter2", source="a test"),
        client=_client(lambda request: httpx.Response(401, text="Unauthorized")),
    )
    (finding,) = log.findings
    assert finding.code == "GBIF_CREDENTIALS_REJECTED"
    assert "'u'" in finding.message
    assert "hunter2" not in finding.message


@pytest.mark.parametrize(("status", "accepted"), [(200, True), (401, False)])
def test_credentials_accepted_is_whether_gbif_answers_for_the_account(status, accepted):
    response = httpx.Response(status, json={"results": []})
    assert gv.credentials_accepted(ACCOUNT, client=_client(lambda request: response)) is accepted


def test_credentials_accepted_raises_when_gbif_cannot_be_reached():
    def unreachable(request):
        raise httpx.ConnectError("no route to host")

    with pytest.raises(httpx.HTTPError):
        gv.credentials_accepted(ACCOUNT, client=_client(unreachable))


def test_run_gbif_validation_reports_issues_from_a_finished_job(zip_path):

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"key": "job-1", "status": "SUBMITTED"})
        return httpx.Response(
            200,
            json={
                "status": "FINISHED",
                "metrics": {
                    "files": [
                        {
                            "issues": [
                                {
                                    "issue": "OCCURRENCE_ID_NOT_UNIQUE",
                                    "count": 3,
                                }
                            ]
                        }
                    ]
                },
            },
        )

    log, issues = gv.run_gbif_validation(zip_path, credentials=ACCOUNT, client=_client(handler))
    assert len(log.findings) == 1
    assert log.findings[0].code == "GBIF_VALIDATOR_ISSUE"
    assert log.findings[0].severity == "info"
    assert issues == [gv.GbifIssue("OCCURRENCE_ID_NOT_UNIQUE", "info", 3)]


def test_run_gbif_validation_applies_an_accepted_adjudication(zip_path):

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"key": "job-1", "status": "SUBMITTED"})
        return httpx.Response(
            200,
            json={
                "status": "FINISHED",
                "metrics": {
                    "files": [
                        {
                            "issues": [
                                {
                                    "issue": "RECORD_REFERENCES_TAXON_MATCH_NONE",
                                    "count": 40,
                                }
                            ]
                        }
                    ]
                },
            },
        )

    log, _ = gv.run_gbif_validation(
        zip_path,
        credentials=ACCOUNT,
        client=_client(handler),
        adjudications={"RECORD_REFERENCES_TAXON_MATCH_NONE": "accepted"},
    )
    assert log.findings[0].code == "STRUCTURAL_COST_DISCLOSED"


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("no network")


def _never_called(request: httpx.Request) -> httpx.Response:  # pragma: no cover
    raise AssertionError("should not attempt a network call for a missing file")


@pytest.mark.parametrize(
    ("zip_name", "handler"),
    [
        ("does_not_exist.zip", _never_called),
        ("dwca.zip", _unreachable),
        ("dwca.zip", lambda request: httpx.Response(200, text="<html>Service Unavailable</html>")),
        ("dwca.zip", lambda request: httpx.Response(200, json={"unexpected": "shape"})),
    ],
    ids=["missing_zip", "network_error", "submit_not_json", "submit_without_key"],
)
def test_run_gbif_validation_reports_the_validator_unavailable_rather_than_failing(
    zip_path, zip_name, handler
):
    log, _ = gv.run_gbif_validation(
        zip_path.with_name(zip_name), credentials=ACCOUNT, client=_client(handler)
    )
    assert [f.code for f in log.findings] == ["GBIF_VALIDATOR_UNAVAILABLE"]


def test_submit_archive_raises_a_gbif_validator_error_on_a_non_json_response(zip_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(gv.GbifValidatorError):
        gv.submit_archive(
            zip_path,
            credentials=ACCOUNT,
            client=_client(handler),
        )


def test_poll_job_raises_after_timeout():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"status": "RUNNING"})

    with pytest.raises(gv.GbifValidatorError):
        gv.poll_job(
            "job-1",
            credentials=ACCOUNT,
            client=_client(handler),
            timeout_seconds=0,
            poll_interval_seconds=10,
            sleep=lambda _s: None,
        )


def test_poll_job_sends_the_same_credentials_it_was_given():
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"status": "FINISHED"})

    gv.poll_job(
        "job-1",
        credentials=ACCOUNT,
        client=_client(handler),
    )

    assert len(seen_requests) == 1
    assert seen_requests[0].headers["authorization"] == httpx.BasicAuth("u", "p")._auth_header
