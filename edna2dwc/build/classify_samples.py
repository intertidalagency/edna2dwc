from __future__ import annotations

from dataclasses import dataclass

from edna2dwc.build.filter_controls import (
    build_roster,
    resolve_classifications,
    samples_seen,
)
from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import Table


@dataclass
class SampleClassification:
    proposal: list[dict[str, str]]
    roster: list[dict[str, str]]
    findings: FindingsLog


def classify(
    table: Table,
    *,
    control_answers: dict[str, str] | None = None,
    sample_types: dict[str, str] | None = None,
    occurrence_type_col: str | None = None,
) -> SampleClassification:
    control_answers = control_answers or {}
    sample_types = sample_types or {}
    samples = samples_seen(table, occurrence_type_col)
    proposed = resolve_classifications(samples, sample_metadata_by_id=sample_types)
    classifications = resolve_classifications(
        samples, sample_metadata_by_id=sample_types, control_answers=control_answers
    )
    roster = build_roster(samples, classifications)

    findings = FindingsLog(list(roster.findings.findings))
    unmatched = sorted(control_answers.keys() - classifications.keys())
    if unmatched:
        findings.add(
            "CONTROL_ANSWER_UNMATCHED",
            f"{len(unmatched)} sampleID(s) under controls: in answers.yaml are not in the "
            f"table: {', '.join(unmatched)}. Each answer settles nothing, so the build stops: "
            "remove it, or correct the sampleID to one the table has, then build again",
            count=len(unmatched),
        )
    return SampleClassification(
        proposal=build_roster(samples, proposed).report_rows,
        roster=roster.report_rows,
        findings=findings,
    )
