from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

from edna2dwc.common import pages
from edna2dwc.common.findings import HALT_CODES, meaning
from edna2dwc.common.table import connect, read_tsv
from edna2dwc.common.tsv import read_header
from edna2dwc.conversion import artifacts
from edna2dwc.dwca import writer
from edna2dwc.dwca.manifest import Manifest
from edna2dwc.terms import term_states
from edna2dwc.validation import validate

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
    "MEASUREMENT_UNIT_OVERRIDDEN",
    "STRUCTURAL_COST_DISCLOSED",
    "CONFIRMED_SHEET_APPLIED",
    "TAXON_OVERRIDDEN",
    "GEOGRAPHIC_COVERAGE_DERIVED",
)

OPEN_QUESTION_CODES = (
    "DECISION_REQUIRED",
    "TAXON_UNRESOLVED",
    "TAXON_FUZZY",
    "TAXON_RANK_WORD_REFUSED",
    "TAXON_MASS_COLLAPSE",
    "TAXON_AMBIGUOUS_HOMONYM",
    "SOURCE_KINGDOM_UNINFORMATIVE",
    "TERM_AMBIGUOUS",
    "CONTROL_AMBIGUOUS",
    "TIMESTAMP_CONFLICT",
    "PROPOSAL_ACCEPTED",
    "CONFIRMED_ROW_UNMATCHED",
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
    "otu_class_appr": "the bioinformatics pipeline's methods notes",
    "otu_seq_comp_appr": "the bioinformatics pipeline's methods notes",
    "otu_db": "the bioinformatics pipeline's methods notes",
    "sop": "the lab's standard operating procedure document",
    "samplingProtocol": "the field sampling log",
    "minimumDepthInMeters": "the field sampling log",
    "maximumDepthInMeters": "the field sampling log",
    "coordinateUncertaintyInMeters": "the field GPS log",
    "recordedBy": "the field sampling log",
    "sampleSizeValue": "the sample metadata sheet",
    "sampleSizeUnit": "the sample metadata sheet",
    "institutionCode": "the dataset's metadata sheet",
    "datasetName": "the dataset's metadata sheet",
}

_REPRODUCE_LINES = (
    "cd reproduce",
    "just replay    # reconstructs the recorded versions, runs build",
    "just check     # the above, then compares the rebuild with the dwca.zip beside reproduce/",
)

_REPRODUCE_NOTE = (
    "Every command above runs from inside `reproduce/`, which sits beside `dwca.zip` and holds "
    "the recipe and the justfile that drives it. `just` is a small command runner, installed "
    "separately from `edna2dwc` (https://github.com/casey/just#installation); without it, open "
    "`justfile` and run the recipe's `edna2dwc` line by hand. Where `reproduce/` is kept apart "
    "from `dwca.zip`, give `just check` the zip's path: `just against=<dwca.zip> check`.\n\n"
    "A divergence under `just check` is expected the moment WoRMS, GBIF's backbone, or PROJ's "
    "datum grids have changed since this archive was built. To see whether taxonomy resolution "
    "is the cause before assuming a real defect, run `edna2dwc resolve-taxonomy --refresh` and "
    "then `edna2dwc build --automatic` in a copy of `reproduce/`, and compare that archive."
)

_TERM_MISSING_PRIORITY_NAME_RE = re.compile(r"^'([^']+)' is filled on \d+ of \d+ rows$")


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
    audit_findings: list[str]
    provenance: dict[str, str]
    confirmed: dict[str, str]

    @classmethod
    def from_dict(cls, raw: dict) -> ConversionReport:
        report = cls(**raw)
        report.extension_types = tuple(raw["extension_types"])
        report.transformations = [CodeGroup(**group) for group in raw["transformations"]]
        report.open_questions = [CodeGroup(**group) for group in raw["open_questions"]]
        return report


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


def _uncurated_groups(findings: list[dict]) -> tuple[list[CodeGroup], list[CodeGroup]]:
    by_code: dict[str, list[dict]] = {}
    for f in findings:
        if f["code"] in TRANSFORMATION_CODES or f["code"] in OPEN_QUESTION_CODES:
            continue
        by_code.setdefault(f["code"], []).append(f)

    transformations: list[CodeGroup] = []
    open_questions: list[CodeGroup] = []
    for code in sorted(by_code):
        group = CodeGroup(
            code=code,
            count=sum(f["count"] for f in by_code[code]),
            example_message=by_code[code][0]["message"],
        )
        needs_a_human = any(f["severity"] in ("error", "warning") for f in by_code[code])
        (open_questions if needs_a_human else transformations).append(group)
    return transformations, open_questions


def _action_items(
    *,
    findings: list[dict],
    open_sheets: int,
    ask_list: list[str],
    blank_metadata: list[str],
    missing_eml_elements: list[str],
    unconfirmed: int,
    archive_filename: str,
) -> list[str]:
    items = []
    to_judge = [f for f in findings if f["code"] == "ADJUDICATION_NEEDED"]
    not_to_resolve = {"ADJUDICATION_NEEDED", *HALT_CODES.values()}
    error_count = sum(
        f["count"]
        for f in findings
        if f["severity"] == "error" and f["code"] not in not_to_resolve
    )
    if error_count:
        items.append(f"Resolve {error_count} error-level finding(s) (see What was transformed).")
    if to_judge:
        items.append(
            f"Judge {len(to_judge)} finding(s): accept each under adjudications: in "
            "answers.yaml as its finding says, or correct the data."
        )
    if open_sheets:
        items.append(f"Review {open_sheets} open proposal(s) (see REVIEW.md).")
    if ask_list:
        fields = ", ".join(ask_list)
        items.append(f"Answer {len(ask_list)} unset metadata field(s): {fields}.")
    if blank_metadata:
        items.append(
            f"Set {len(blank_metadata)} blank metadata field(s): {', '.join(blank_metadata)}."
        )
    if missing_eml_elements:
        elements = ", ".join(f"<{element}>" for element in missing_eml_elements)
        items.append(
            f"eml.xml has no {elements}, which GBIF's EML profile requires. Set the blank "
            "field(s) in answers.yaml before publishing."
        )
    if unconfirmed:
        items.append(
            f"Confirm {unconfirmed} answer(s) no person has confirmed, listed in "
            "REVIEW.md: put the person's reply in each confirmed:, or leave it empty with "
            "nobody to ask."
        )
    items.append(f"Upload {archive_filename} to the target repository once the above are done.")
    return items


def _recommendations(findings: list[dict]) -> list[str]:
    recs: list[str] = []
    for f in findings:
        if f["code"] in ("TERM_MISSING_PRIORITY", "TERM_MISSING_RECOMMENDED"):
            match = _TERM_MISSING_PRIORITY_NAME_RE.match(f["message"])
            if match:
                term = match.group(1)
                location = RECORDING_LOCATIONS.get(term)
                if location:
                    recs.append(f"Record {term} next time, in {location}.")
                else:
                    recs.append(
                        f"Record {term} next time. No specific place to record it is known yet."
                    )
            else:
                recs.append(f"Future datasets: {f['message']}")
    return list(dict.fromkeys(recs))


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
    open_sheets: int,
    ask_list: list[str],
    provenance: dict[str, str],
    confirmed: dict[str, str] | None = None,
    blank_metadata: list[str] | None = None,
    missing_eml_elements: list[str] | None = None,
    unconfirmed: int = 0,
    audit_findings: list[str] | None = None,
    audit_stale: bool = False,
    term_state_counts: dict[str, int] | None = None,
) -> ConversionReport:

    extra_transformations, extra_open_questions = _uncurated_groups(findings)

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
            open_sheets=open_sheets,
            ask_list=ask_list,
            blank_metadata=list(blank_metadata or []),
            missing_eml_elements=list(missing_eml_elements or []),
            unconfirmed=unconfirmed,
            archive_filename=archive_filename,
        ),
        transformations=_group_by_code(findings, TRANSFORMATION_CODES) + extra_transformations,
        open_questions=_group_by_code(findings, OPEN_QUESTION_CODES) + extra_open_questions,
        recommendations=_recommendations(findings),
        audit_summary=_audit_summary(audit_findings, audit_stale),
        audit_findings=list(audit_findings or []),
        provenance=dict(provenance),
        confirmed=dict(confirmed or {}),
    )


def _audit_summary(findings: list[str] | None, stale: bool) -> str:
    if findings is None:
        return "not recorded"
    summary = f"{len(findings)} finding(s) recorded"
    if stale:
        summary += (
            " against an earlier build of this archive, so a finding below may be fixed "
            "already or missed by it; audit again before publishing"
        )
    return summary


def _code_group_line(group: CodeGroup) -> str:
    explanation = meaning(group.code).rstrip(".")
    return (
        f"- **{group.code}** ({group.count}): {explanation}. For example: {group.example_message}"
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
            lines.append(_code_group_line(t))
    else:
        lines.append("Nothing to report.")
    lines.append("")

    lines += ["## 4. Open questions", ""]
    if report.open_questions:
        for q in report.open_questions:
            lines.append(_code_group_line(q))
    else:
        lines.append("Nothing to report.")
    lines.append("")

    lines += ["## 5. Recommendations for future datasets", ""]
    if report.recommendations:
        lines += _numbered(report.recommendations)
        lines.append("")
        lines.append(
            "The recording locations above are this tool's suggestions. "
            "No domain expert has reviewed them yet."
        )
    else:
        lines.append("Nothing to report.")
    lines.append("")

    lines += ["## 6. Provenance and audit", ""]
    lines.append(f"- Fabrication audit: {report.audit_summary}")
    for audit_finding in report.audit_findings:
        lines.append(f"  - {audit_finding}")
    for field_name, provenance in sorted(report.provenance.items()):
        confirmed = report.confirmed.get(field_name)
        reply = f"; confirmed: {confirmed}" if confirmed else "; not confirmed by a person"
        lines.append(f"  - {field_name}: {provenance}{reply}")
    lines.append("")

    lines += ["## 7. How to reproduce", ""]
    lines += [f"    {line}" for line in _REPRODUCE_LINES]
    lines.append("")
    lines.append(_REPRODUCE_NOTE)
    lines.append("")

    return "\n".join(lines)


_ROW_TYPE_SHORT_NAMES = {uri: key for key, uri in writer.ROW_TYPE_URIS.items()}


def write(
    *,
    archive_dir: Path,
    archive_name: Path,
    findings: list[dict],
    metadata: Manifest,
    open_sheets: int,
    blank_metadata: list[str],
    missing_eml_elements: list[str],
    unconfirmed: int,
    audit: tuple[list[str], bool] | None,
    states: list[term_states.TermState],
    record_count: int | None = None,
    sample_count: int | None = None,
) -> list[Path]:
    tables = validate.parse_meta_xml(archive_dir / "meta.xml")
    core_table = next(t for t in tables if t.is_core)
    if record_count is None:
        core_path = archive_dir / core_table.file_location
        core_header = read_header(core_path, delimiter="\t")
        with connect() as con:
            core = read_tsv(con, core_path, "report_core", core_header)
            record_count, sample_count = validate.record_and_sample_counts(core, core_header)
    extension_types = tuple(
        _ROW_TYPE_SHORT_NAMES.get(t.row_type, t.row_type) for t in tables if not t.is_core
    )

    term_state_counts: dict[str, int] = {}
    for state in states:
        label = state.state or term_states.NO_STATE_LABEL
        term_state_counts[label] = term_state_counts.get(label, 0) + 1
    conversion_report = build_report(
        dataset_title=metadata.values.get("title", ""),
        archive_path=str(archive_name),
        archive_filename=artifacts.ZIP_NAME,
        core_type=_ROW_TYPE_SHORT_NAMES.get(core_table.row_type, core_table.row_type),
        extension_types=extension_types,
        record_count=record_count,
        sample_count=sample_count,
        findings=findings,
        open_sheets=open_sheets,
        ask_list=metadata.ask_list(),
        provenance=metadata.provenance,
        confirmed=metadata.confirmed,
        blank_metadata=blank_metadata,
        missing_eml_elements=missing_eml_elements,
        unconfirmed=unconfirmed,
        audit_findings=None if audit is None else audit[0],
        audit_stale=audit is not None and audit[1],
        term_state_counts=term_state_counts,
    )
    return _write_pages(archive_dir, conversion_report)


def _write_pages(archive_dir: Path, conversion_report: ConversionReport) -> list[Path]:
    data = archive_dir / artifacts.REPORT_DATA_FILENAME
    data.write_text(json.dumps(asdict(conversion_report), indent=2), encoding="utf-8")
    return [
        *pages.write_page(
            archive_dir / artifacts.REPORT_FILENAME, render_markdown(conversion_report)
        )
    ]


def record_audit(archive_dir: Path, audit_findings: list[str]) -> list[Path] | None:
    data = archive_dir / artifacts.REPORT_DATA_FILENAME
    if not data.exists():
        return None
    conversion_report = ConversionReport.from_dict(json.loads(data.read_text(encoding="utf-8")))
    conversion_report.audit_summary = _audit_summary(audit_findings, False)
    conversion_report.audit_findings = list(audit_findings)
    return _write_pages(archive_dir, conversion_report)
