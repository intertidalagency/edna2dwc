from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
import time

import httpx

from edna2dwc.common.findings import FindingsLog
from edna2dwc.validation.credentials import (
    MISSING,
    PARTIAL,
    REJECTED,
    SET_HINT,
    UNREADABLE,
    Credentials,
    Unavailable,
)

BASE_URL = "https://api.gbif.org/v1/validation"
DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 300
TERMINAL_STATUSES = frozenset({"FINISHED", "FAILED", "ABORTED"})
UNAUTHORIZED = 401
NO_VERDICT_CODES = frozenset(
    {"GBIF_VALIDATOR_UNAVAILABLE", MISSING, PARTIAL, UNREADABLE, REJECTED}
)

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


GbifValidation = Callable[[Path, dict[str, str]], tuple[FindingsLog, list[GbifIssue]]]


class GbifValidatorError(RuntimeError):
    pass


def _rejected(error: Exception) -> bool:
    return isinstance(error, httpx.HTTPStatusError) and error.response.status_code == UNAUTHORIZED


def _not_measured(error: Exception, credentials: Credentials) -> tuple[str, str]:
    if _rejected(error):
        return (
            REJECTED,
            (
                f"GBIF rejected the account {credentials.username!r} from "
                f"{credentials.source}; GBIF validation not measured this run. {SET_HINT} to "
                "replace it"
            ),
        )
    return "GBIF_VALIDATOR_UNAVAILABLE", f"GBIF validation not measured this run: {error}"


def credentials_accepted(credentials: Credentials, *, client: httpx.Client | None = None) -> bool:
    owns_client = client is None
    client = client or httpx.Client(timeout=30)
    try:
        response = client.get(
            BASE_URL,
            params={"limit": 1},
            auth=(credentials.username, credentials.password),
        )
        if response.status_code == UNAUTHORIZED:
            return False
        response.raise_for_status()
        return True
    finally:
        if owns_client:
            client.close()


def submit_archive(zip_path, *, credentials: Credentials, client: httpx.Client) -> str:
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
    credentials: Credentials,
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
    zip_path: Path,
    *,
    credentials: Credentials | Unavailable,
    client: httpx.Client,
    adjudications: dict[str, str] | None = None,
) -> tuple[FindingsLog, list[GbifIssue]]:
    log = FindingsLog()
    if isinstance(credentials, Unavailable):
        log.add(credentials.code, credentials.detail)
        return log, []

    try:
        job_key = submit_archive(zip_path, credentials=credentials, client=client)
        result = poll_job(job_key, credentials=credentials, client=client)
    except (httpx.HTTPError, GbifValidatorError, OSError) as exc:
        log.add(*_not_measured(exc, credentials))
        return log, []

    adjudications = adjudications or {}
    issues = parse_issues(result)
    for issue in issues:
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
    return log, issues
