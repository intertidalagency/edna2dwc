from __future__ import annotations

from dataclasses import dataclass, field



def _to_float(value: str) -> float | None:
    try:
    except (TypeError, ValueError):
        return None




    findings = FindingsLog()




    if missing_status:
        findings.add(
            count=missing_status,
        )


def resolve_conflicting_timestamps(
    findings = FindingsLog()
        findings.add(
            "TIMESTAMP_CONFLICT",
            f"{conflicts} row(s) have disagreeing {col_a}/{col_b} timestamps",
            count=conflicts,
        )


