from __future__ import annotations

from dataclasses import dataclass
import json
import time

import httpx


BASE_URL = "https://api.gbif.org/v1/validation"
DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 300
TERMINAL_STATUSES = frozenset({"FINISHED", "FAILED", "ABORTED"})

_SEVERITY_MAP = {"ERROR": "error", "WARNING": "warning"}


def gbif_severity_for(gbif_severity: str) -> str:
    return _SEVERITY_MAP.get(gbif_severity, "info")


@dataclass(frozen=True)
class GbifIssue:
    category: str
    severity: str
    affected_records: int


def parse_issues(result: dict) -> list[GbifIssue]:
    issues = []
    for file_info in (result.get("metrics") or {}).get("files") or []:
        for issue in file_info.get("issues") or []:
            issues.append(
                GbifIssue(
                    category=issue.get("issue", "UNKNOWN"),
                    severity=gbif_severity_for(issue.get("severity", "INFO")),
                    affected_records=issue.get("count", 0),
                )
            )
    return issues


class GbifValidatorError(RuntimeError):


    with open(zip_path, "rb") as f:
        response = client.post(
            BASE_URL,
            auth=(credentials.username, credentials.password),
            files={"file": (zip_path.name, f, "application/zip")},
        )
    response.raise_for_status()
    try:
        return response.json()["key"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise GbifValidatorError(
            f"GBIF submit response was not the expected shape: {exc}"
        ) from exc


def poll_job(
    job_key: str,
    *,
    client: httpx.Client,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    sleep=time.sleep,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while True:
        response = client.get(
            f"{BASE_URL}/{job_key}", auth=(credentials.username, credentials.password)
        )
        response.raise_for_status()
        try:
            result = response.json()
        except json.JSONDecodeError as exc:
            raise GbifValidatorError(f"GBIF poll response was not JSON: {exc}") from exc
        if result.get("status") in TERMINAL_STATUSES:
            return result
        if time.monotonic() >= deadline:
            raise GbifValidatorError(
                f"GBIF validation job {job_key!r} did not finish within {timeout_seconds}s"
            )
        sleep(poll_interval_seconds)


def run_gbif_validation(
    *,
    adjudications: dict[str, str] | None = None,
    log = FindingsLog()

    try:

    adjudications = adjudications or {}
        if adjudications.get(issue.category) == "accepted":
            log.add(
                "STRUCTURAL_COST_DISCLOSED",
                f"GBIF {issue.category}: {issue.affected_records} record(s), accepted as a "
                "disclosed structural cost",
                count=issue.affected_records,
            )
        else:
            log.add(
                "GBIF_VALIDATOR_ISSUE",
                f"GBIF {issue.category}: {issue.affected_records} record(s)",
                severity=issue.severity,
                count=issue.affected_records,
            )
