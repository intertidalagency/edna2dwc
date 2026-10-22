from __future__ import annotations

import zipfile

import httpx
import pytest



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

    assert len(log.findings) == 1
    assert log.findings[0].code == "GBIF_VALIDATOR_ISSUE"
    assert log.findings[0].severity == "info"



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

        zip_path,
        client=_client(handler),
        adjudications={"RECORD_REFERENCES_TAXON_MATCH_NONE": "accepted"},
    )
    assert log.findings[0].code == "STRUCTURAL_COST_DISCLOSED"




def test_submit_archive_raises_a_gbif_validator_error_on_a_non_json_response(zip_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(gv.GbifValidatorError):
        gv.submit_archive(
            zip_path,
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
            client=_client(handler),
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
        client=_client(handler),
    )

    assert len(seen_requests) == 1
    assert seen_requests[0].headers["authorization"] == httpx.BasicAuth("u", "p")._auth_header
