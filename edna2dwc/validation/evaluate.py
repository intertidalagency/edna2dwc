from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from edna2dwc.common import pages
from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.result import CommandResult
from edna2dwc.common.table import connect
from edna2dwc.conversion import answers, artifacts
from edna2dwc.review import audit
from edna2dwc.terms import map_terms
from edna2dwc.validation import gates, validate
from edna2dwc.validation.gbif_validator import GbifValidation

PAGE_NAME = "EVALUATION.md"

TIER_LABELS = {"required": "required", "strongly_recommended": "strongly recommended"}

NOT_MEASURED = "not measured"
VALIDATOR_VERDICTS = {True: "accept", False: "reject", None: NOT_MEASURED}
STRUCTURAL_CODE = "ARCHIVE_INVALID"

GATE_CHECKS = {
    "required_terms": ("Every required term is filled on every row", ""),
    "strongly_recommended_terms": ("Every strongly recommended term is filled on every row", ""),
    "valid_darwin_core_terms": ("Every column is a Darwin Core term", ""),
    "mapping_description": (
        "Every mapped column has a traceable method",
        "term_mapping.tsv not found",
    ),
    "every_term_has_a_state": ("Every term has a recorded state", "term_states.tsv not found"),
    "row_accounting": ("Every row is accounted for", "occurrence_long.tsv not found"),
}
ADVISORY_GATES = frozenset({"strongly_recommended_terms"})


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool | None
    detail: str
    advisory: bool = False

    @property
    def result(self) -> str:
        if self.passed is None:
            return NOT_MEASURED
        return "passed" if self.passed else "failed"


@dataclass(frozen=True)
class MissingTerm:
    term: str
    tier: str
    build_tier: str
    filled: str
    state: str
    evidence: str


@dataclass(frozen=True)
class FindingGroup:
    code: str
    count: int
    example: str


@dataclass
class Evaluation:
    archive_path: str
    record_count: int
    sample_count: int | None
    checks: list[Check]
    missing_terms: list[MissingTerm]
    findings: list[FindingGroup]
    gbif: gates.ValidatorResult
    obis: gates.ValidatorResult
    coverage: dict[str, int] | None
    audit: tuple[list[str], bool] | None
    inputs: dict[str, str | None]

    @property
    def audit_findings(self) -> list[str] | None:
        return None if self.audit is None else self.audit[0]

    @property
    def audit_stale(self) -> bool:
        return self.audit is not None and self.audit[1]

    @property
    def all_checks_passed(self) -> bool:
        return all(check.passed for check in self.checks if not check.advisory)

    @property
    def passes_gbif_obis(self) -> bool | None:
        if not (self.gbif.ran and self.obis.ran):
            return None
        return not (self.gbif.errors or self.obis.errors)

    @property
    def validator_verdict(self) -> str:
        return f"GBIF and OBIS validators: {VALIDATOR_VERDICTS[self.passes_gbif_obis]}"

    def to_dict(self) -> dict:
        return {
            "archive_path": self.archive_path,
            "record_count": self.record_count,
            "sample_count": self.sample_count,
            "all_checks_passed": self.all_checks_passed,
            "passes_gbif_obis": self.passes_gbif_obis,
            "checks": [asdict(check) for check in self.checks],
            "missing_terms": [asdict(term) for term in self.missing_terms],
            "findings": [asdict(group) for group in self.findings],
            "gbif": _validator_dict(self.gbif),
            "obis": _validator_dict(self.obis),
            "coverage": self.coverage,
            "audit_findings": self.audit_findings,
            "audit_stale": self.audit_stale,
            "inputs": self.inputs,
        }


def _validator_dict(result: gates.ValidatorResult) -> dict:
    return {"ran": result.ran, "detail": result.detail, "errors": result.errors}


def conversion_dir(archive_dir: Path) -> Path:
    archive = archive_dir.resolve()
    for candidate in archive.parents:
        answers_path = candidate / artifacts.ANSWERS
        out_dir = answers_path.exists() and answers.declared_out_dir(answers_path)
        if out_dir and (candidate / out_dir).resolve() == archive:
            return candidate
    return Path()


def find_input(root: Path, name: Path, override: Path | None) -> Path | None:
    path = root / name
    return override or (path if path.exists() else None)


def bundled_adjudications(archive_dir: Path) -> Path | None:
    answers_path = archive_dir / artifacts.BUNDLE_DIR / artifacts.ANSWERS
    if not answers_path.exists():
        return None
    return answers_path if answers.declared(answers_path, "adjudications") else None


def _group(findings: list) -> list[FindingGroup]:
    groups: dict[str, FindingGroup] = {}
    for finding in findings:
        existing = groups.get(finding.code)
        groups[finding.code] = FindingGroup(
            finding.code,
            (existing.count if existing else 0) + finding.count,
            existing.example if existing else finding.message,
        )
    return list(groups.values())


def _coverage(mapping_path: Path | None) -> dict[str, int] | None:
    if mapping_path is None:
        return None
    proposals = map_terms.read_mapping_tsv(mapping_path.read_text(encoding="utf-8"))
    counts = {"mapped": 0, "dynamicProperties": 0, "excluded": 0, "unmapped": 0}
    for proposal in proposals:
        if proposal.target == "dynamicProperties":
            counts["dynamicProperties"] += 1
        elif proposal.target:
            counts["mapped"] += 1
        elif proposal.basis == "internal":
            counts["excluded"] += 1
        else:
            counts["unmapped"] += 1
    return counts


def _validator_check(name: str, result: gates.ValidatorResult, *, advisory: bool = False) -> Check:
    if not result.ran:
        return Check(name, None, result.detail, advisory)
    total = sum(result.errors.values())
    if total:
        return Check(
            name, False, f"{total} record-level error(s) in {len(result.errors)} class(es)"
        )
    return Check(name, True, "")


def _gate_checks(measured: gates.Gates) -> list[Check]:
    checks = []
    for key, (name, unmeasured_reason) in GATE_CHECKS.items():
        gate: gates.Gate | None = getattr(measured, key)
        advisory = key in ADVISORY_GATES
        if gate is None:
            checks.append(Check(name, None, unmeasured_reason, advisory))
        else:
            checks.append(Check(name, gate[0], gate[1], advisory))
    return checks


def _broken_checks(reason: str) -> list[Check]:
    return [
        Check(name, None, reason, key in ADVISORY_GATES) for key, (name, _) in GATE_CHECKS.items()
    ] + [Check("Values are in the right format", None, reason)]


def evaluate_archive(
    archive_dir: Path,
    term_table: dict,
    *,
    mapping_path: Path | None,
    term_states_path: Path | None,
    intermediate_path: Path | None,
    excluded_report_path: Path | None,
    adjudications_path: Path | None,
    gbif: GbifValidation | None,
) -> Evaluation:
    inputs = {
        "mapping": str(mapping_path) if mapping_path else None,
        "term_states": str(term_states_path) if term_states_path else None,
        "intermediate": str(intermediate_path) if intermediate_path else None,
        "excluded_report": str(excluded_report_path) if excluded_report_path else None,
        "adjudications": str(adjudications_path) if adjudications_path else None,
    }
    states = gates.load_term_states(term_states_path)
    adjudications = validate.load_adjudications(adjudications_path)

    with connect() as con:
        try:
            structural = validate.validate_archive(
                archive_dir, term_table, strict=True, connection=con
            )
            tables = gates.read_tables(archive_dir, term_table, con)
            broken = ""
        except validate.ArchiveInvalidError as error:
            structural = FindingsLog()
            tables = gates.ArchiveTables([], None, [], 0, 0)
            broken = str(error)

        structural_errors = [
            f.message
            for f in structural.findings
            if f.severity == "error" and f.code == STRUCTURAL_CODE
        ]
        checks = [
            Check(
                "Archive structure is valid",
                not broken and not structural_errors,
                broken or "; ".join(structural_errors),
            )
        ]

        missing_terms: list[MissingTerm] = []
        if broken:
            checks += _broken_checks(broken)
        else:
            measured = gates.check_gates(
                tables,
                term_table,
                states=states,
                mapping_path=mapping_path,
                term_states_path=term_states_path,
                intermediate_path=intermediate_path,
                excluded_report_path=excluded_report_path,
            )
            checks += _gate_checks(measured)
            checks.append(
                Check(
                    "Values are in the right format",
                    tables.format_failed == 0,
                    f"{tables.format_failed} of {tables.format_checked} checked values failed"
                    if tables.format_failed
                    else "",
                )
            )
            by_term = {s.term: s for s in states}
            for missing in validate.unfilled_priority_terms(
                tables.fill,
                term_table,
                excused_terms=gates.excused_terms(states, term_table),
            ):
                state = by_term.get(missing.term)
                missing_terms.append(
                    MissingTerm(
                        missing.term,
                        TIER_LABELS[missing.tier],
                        term_table[missing.term].get("tier", "").replace("_", " "),
                        missing.share,
                        state.state if state else "",
                        state.evidence if state else "",
                    )
                )

        if gbif is None:
            gbif_result = gates.ValidatorResult(
                ran=False, detail="not run; evaluate --gbif runs it"
            )
        elif broken:
            gbif_result = gates.ValidatorResult(ran=False, detail=broken)
        else:
            gbif_result = gates.run_gbif(archive_dir, adjudications, gbif)
        obis_result = (
            gates.run_obis(tables, adjudications)
            if tables.record_count
            else gates.ValidatorResult(ran=False, detail="the archive has no readable core table")
        )
        checks.append(
            _validator_check(
                "GBIF validator reports no errors", gbif_result, advisory=gbif is None
            )
        )
        checks.append(_validator_check("OBIS checks report no errors", obis_result))

    return Evaluation(
        archive_path=str(archive_dir),
        record_count=tables.record_count,
        sample_count=tables.sample_count,
        checks=checks,
        missing_terms=missing_terms,
        findings=_group(structural.findings),
        gbif=gbif_result,
        obis=obis_result,
        coverage=_coverage(mapping_path),
        audit=audit.load_recorded_audit(
            archive_dir / artifacts.BUNDLE_DIR / artifacts.AUDIT_RECORD, archive_dir=archive_dir
        ),
        inputs=inputs,
    )


def render_markdown(evaluation: Evaluation) -> str:
    deciding = [c for c in evaluation.checks if not c.advisory]
    passed = sum(1 for c in deciding if c.passed is True)
    failed = sum(1 for c in deciding if c.passed is False)
    unmeasured = sum(1 for c in deciding if c.passed is None)
    lines = [f"# Evaluation of {evaluation.archive_path}", ""]
    lines.append(f"- Records: {evaluation.record_count}")
    if evaluation.sample_count is not None:
        lines.append(f"- Samples: {evaluation.sample_count}")
    lines.append(f"- {evaluation.validator_verdict}.")
    lines.append(
        f"- Checks: {passed} passed, {failed} failed, {unmeasured} not measured. "
        "A check that was not measured does not count as passed. "
        "An advisory check is reported and does not decide the exit code."
    )
    lines.append("")

    lines += ["## Checks", ""]
    lines += pages.table(
        ["Check", "Result", "Detail"],
        [
            [c.name + (" (advisory)" if c.advisory else ""), c.result, c.detail]
            for c in evaluation.checks
        ],
    )
    lines.append("")

    lines += ["## Missing terms", ""]
    if evaluation.missing_terms:
        lines.append(
            "Priority eDNA terms rated required or strongly recommended that some row of the "
            "archive leaves blank, with the share of rows that fill each. Tier is the eDNA "
            "list's rating, not a registry's. Build tier is the term table's: `required` marks "
            "`occurrenceID`, `basisOfRecord` and `scientificName`, the terms GBIF rejects an "
            "archive without. A recorded state is what the conversion said about the term; it "
            "is information for the researcher and excuses nothing here, except Not-applicable "
            "for a term the study design rules out."
        )
        lines.append("")
        lines += pages.table(
            ["Term", "Tier", "Build tier", "Filled", "Recorded state", "Evidence"],
            [
                [f"`{m.term}`", m.tier, m.build_tier, m.filled, m.state or "none", m.evidence]
                for m in evaluation.missing_terms
            ],
        )
    else:
        lines.append(
            "Every priority eDNA term rated required or strongly recommended is filled on "
            "every row."
        )
    lines.append("")

    lines += ["## Findings", ""]
    if evaluation.findings:
        lines += pages.table(
            ["Finding", "Count", "Example"],
            [[f"`{g.code}`", str(g.count), g.example] for g in evaluation.findings],
        )
    else:
        lines.append("Nothing to report.")
    lines.append("")

    for title, result in (("GBIF validator", evaluation.gbif), ("OBIS checks", evaluation.obis)):
        lines += [f"## {title}", ""]
        if not result.ran:
            lines.append(f"Not measured: {result.detail}.")
        elif result.errors:
            lines += pages.table(
                ["Error class", "Records"],
                [[f"`{k}`", str(v)] for k, v in sorted(result.errors.items())],
            )
        else:
            lines.append("No errors.")
        lines.append("")

    lines += ["## Where the source columns went", ""]
    if evaluation.coverage is None:
        lines.append("Not measured: term_mapping.tsv not found.")
    else:
        c = evaluation.coverage
        lines += pages.table(
            ["Disposition", "Columns"],
            [
                ["Mapped to a Darwin Core or extension term", str(c["mapped"])],
                ["Mapped to `dynamicProperties`", str(c["dynamicProperties"])],
                ["Left out on purpose", str(c["excluded"])],
                ["Mapped to no term, so in eMoF or `dynamicProperties`", str(c["unmapped"])],
            ],
        )
    lines.append("")

    lines += ["## Fabrication audit", ""]
    if evaluation.audit_findings is None:
        lines.append("Not recorded.")
    elif evaluation.audit_findings:
        lines.append(
            "An independent reader's findings, for you to judge. They don't affect any check."
            + (
                " They were recorded against an earlier build of this archive: audit again."
                if evaluation.audit_stale
                else ""
            )
        )
        lines.append("")
        lines += [f"- {finding}" for finding in evaluation.audit_findings]
    else:
        lines.append(
            "Recorded with no findings"
            + (
                ", against an earlier build of this archive: audit again."
                if evaluation.audit_stale
                else "."
            )
        )
    lines.append("")

    todo = [c for c in evaluation.checks if c.passed is not True]
    lines += ["## What to do next", ""]
    if todo:
        lines += [f"- **{c.name}**: {c.detail or c.result}." for c in todo]
        lines.append("")
        lines.append(
            "Close a check with a value a source states, or leave it failed and tell the "
            "researcher. A value chosen to pass a check, such as a geodetic datum no document "
            "gives, is a fabrication."
        )
    else:
        lines.append("Nothing. Every check passed.")
    lines.append("")
    return "\n".join(lines)


def step(
    *,
    archive_dir: Path,
    term_table: dict,
    mapping_path: Path | None,
    term_states_path: Path | None,
    intermediate_path: Path | None,
    excluded_report_path: Path | None,
    adjudications_path: Path | None,
    gbif: GbifValidation | None,
    as_json: bool,
) -> CommandResult:
    root = conversion_dir(archive_dir)
    evaluation = evaluate_archive(
        archive_dir,
        term_table,
        mapping_path=find_input(root, artifacts.MAPPING, mapping_path),
        term_states_path=find_input(root, artifacts.TERM_STATES, term_states_path),
        intermediate_path=find_input(root, artifacts.INTERMEDIATE, intermediate_path),
        excluded_report_path=find_input(
            root, artifacts.EXCLUDED_ROWS_REPORT, excluded_report_path
        ),
        adjudications_path=adjudications_path or bundled_adjudications(archive_dir),
        gbif=gbif,
    )
    written = pages.write_page(archive_dir / PAGE_NAME, render_markdown(evaluation))
    summary = [
        f"{c.name}: {c.result}" + (f" ({c.detail})" if c.detail else "") for c in evaluation.checks
    ]
    summary.append(f"{evaluation.validator_verdict}.")
    summary.append(f"Wrote {written[0]} and {written[1]}.")
    return CommandResult(
        command="evaluate",
        status="ok" if evaluation.all_checks_passed else "checks_failed",
        json_body=evaluation.to_dict(),
        outputs={"page": str(written[0])},
        text="\n".join(summary),
        next_step=f"close what {PAGE_NAME} lists, then go over the archive with the researcher",
        as_json=as_json,
        exit_code=0 if evaluation.all_checks_passed else 1,
    )
