from __future__ import annotations

import re

TRANSFORMATION_CODES = (
    "PRESENCE_ONLY_FILTERED",
    "CONTROL_EXCLUDED",
    "CONTAMINANT_EXCLUDED",
    "HUMAN_EXCLUDED",
    "TAXON_UNRESOLVED",
    "TAXON_FUZZY",
    "TAXON_REJECTED_KINGDOM",
    "TAXON_REJECTED_ORGANELLE",
    "TAXON_HOMONYM_DISAMBIGUATED",
    "TAXON_LABEL_STALE",
    "TERM_UNMAPPED",
    "DYNAMIC_PROPERTIES_KEY_COLLISION",
    "CONSTANT_OVERWROTE_MAPPED_VALUE",
    "EMOF_TYPE_UNVOCABULARIED",
    "STRUCTURAL_COST_DISCLOSED",
)

OPEN_QUESTION_CODES = (
    "DECISION_REQUIRED",
    "TAXON_UNRESOLVED",
    "TAXON_FUZZY",
    "TAXON_AMBIGUOUS_HOMONYM",
    "SOURCE_KINGDOM_UNINFORMATIVE",
    "TERM_AMBIGUOUS",
    "CONTROL_AMBIGUOUS",
    "TIMESTAMP_CONFLICT",
    "ENVIRONMENT_UNAVAILABLE",
)

RECORDING_LOCATIONS: dict[str, str] = {
    "target_gene": "the sequencing facility's run metadata or methods write-up",
    "target_subfragment": "the sequencing facility's run metadata or methods write-up",
    "pcr_primer_forward": "the PCR/library-prep protocol",
    "pcr_primer_reverse": "the PCR/library-prep protocol",
    "pcr_primer_name_forward": "the PCR/library-prep protocol",
    "pcr_primer_name_reverse": "the PCR/library-prep protocol",
    "pcr_primer_reference": "the PCR/library-prep protocol",
    "annealingTemp": "the sample metadata sheet, alongside PCR conditions",
    "annealingTempUnit": "the sample metadata sheet, alongside PCR conditions",
    "pcr_cond": "the sample metadata sheet, alongside annealing temperature",
    "seq_meth": "the sequencing facility's run report",
    "sop": "the lab's standard operating procedure document",
    "samplingProtocol": "the field sampling log",
    "minimumDepthInMeters": "the field sampling log",
    "maximumDepthInMeters": "the field sampling log",
    "coordinateUncertaintyInMeters": "the field GPS log",
    "recordedBy": "the field sampling log",
    "sampleSizeValue": "the sample metadata sheet",
    "sampleSizeUnit": "the sample metadata sheet",
}

_REPRODUCE_LINES = (
)

_REPRODUCE_NOTE = (
)



@dataclass
class CodeGroup:
    code: str
    count: int
    example_message: str


@dataclass
class ConversionReport:
    dataset_title: str
    archive_path: str
    core_type: str
    extension_types: tuple[str, ...]
    record_count: int
    sample_count: int | None
    term_state_counts: dict[str, int] | None
    action_items: list[str]
    transformations: list[CodeGroup]
    open_questions: list[CodeGroup]
    recommendations: list[str]
    audit_summary: str
    provenance: dict[str, str]


def _group_by_code(findings: list[dict], codes: tuple[str, ...]) -> list[CodeGroup]:
    by_code: dict[str, list[dict]] = {}
    for f in findings:
        if f["code"] in codes:
            by_code.setdefault(f["code"], []).append(f)
    return [
        CodeGroup(
            code=code,
            count=sum(f["count"] for f in by_code[code]),
            example_message=by_code[code][0]["message"],
        )
        for code in codes
        if code in by_code
    ]


def _action_items(
    *,
    findings: list[dict],
    ask_list: list[str],
    archive_filename: str,
) -> list[str]:
    items = []
    if error_count:
        items.append(f"Resolve {error_count} error-level finding(s) (see What was transformed).")
    if ask_list:
        fields = ", ".join(ask_list)
        items.append(f"Answer {len(ask_list)} unset metadata field(s): {fields}.")
    items.append(f"Upload {archive_filename} to the target repository once the above are done.")
    return items


def _recommendations(findings: list[dict]) -> list[str]:
    for f in findings:
            if match:
                term = match.group(1)
                location = RECORDING_LOCATIONS.get(term)
                if location:
                else:
            else:
                recs.append(f"Future datasets: {f['message']}")


def build_report(
    *,
    dataset_title: str,
    archive_path: str,
    archive_filename: str,
    core_type: str,
    extension_types: tuple[str, ...],
    record_count: int,
    sample_count: int | None,
    findings: list[dict],
    ask_list: list[str],
    provenance: dict[str, str],
    term_state_counts: dict[str, int] | None = None,
) -> ConversionReport:

    return ConversionReport(
        dataset_title=dataset_title,
        archive_path=archive_path,
        core_type=core_type,
        extension_types=extension_types,
        record_count=record_count,
        sample_count=sample_count,
        term_state_counts=term_state_counts,
        action_items=_action_items(
            findings=findings,
            ask_list=ask_list,
            archive_filename=archive_filename,
        ),
        recommendations=_recommendations(findings),
        provenance=dict(provenance),
    )


def _numbered(lines: list[str]) -> list[str]:
    return [f"{i}. {line}" for i, line in enumerate(lines, start=1)] or ["Nothing to report."]


def render_markdown(report: ConversionReport) -> str:
    lines = [f"# Conversion report: {report.dataset_title}", ""]

    lines += ["## 1. What this is", ""]
    lines.append(f"- Archive: `{report.archive_path}`")
    lines.append(
        f"- Core: `{report.core_type}`"
        + (f"; extensions: {', '.join(report.extension_types)}" if report.extension_types else "")
    )
    lines.append(f"- Records: {report.record_count}")
    if report.sample_count is not None:
        lines.append(f"- Samples: {report.sample_count}")
    if report.term_state_counts is not None:
        counts = ", ".join(
            f"{state}: {n}" for state, n in sorted(report.term_state_counts.items())
        )
        lines.append(f"- Term states: {counts}")
    lines.append("")

    lines += ["## 2. Action items", ""]
    lines += _numbered(report.action_items)
    lines.append("")

    lines += ["## 3. What was transformed", ""]
    if report.transformations:
        for t in report.transformations:
    else:
        lines.append("Nothing to report.")
    lines.append("")

    lines += ["## 4. Open questions", ""]
    if report.open_questions:
        for q in report.open_questions:
    else:
        lines.append("Nothing to report.")
    lines.append("")

    lines += ["## 5. Recommendations for future datasets", ""]
    if report.recommendations:
        lines += _numbered(report.recommendations)
        lines.append("")
        lines.append(
        )
    else:
        lines.append("Nothing to report.")
    lines.append("")

    lines += ["## 6. Provenance and audit", ""]
    lines.append(f"- Fabrication audit: {report.audit_summary}")
    lines.append("")

    lines += ["## 7. How to reproduce", ""]
    lines += [f"    {line}" for line in _REPRODUCE_LINES]
    lines.append("")
    lines.append(_REPRODUCE_NOTE)
    lines.append("")

    return "\n".join(lines)
