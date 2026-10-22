from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import Table, literal
from edna2dwc.common.tsv import write_tsv
from edna2dwc.terms import map_terms


class TermSpecError(ValueError):
    pass


AssayType = Literal["metabarcoding", "targeted_assay"]
ASSAY_TYPES = get_args(AssayType)

NO_STATE = ""
NO_STATE_LABEL = "no state"

MAPPED_TABLE_EVIDENCE = "mapped occurrence table"
ABSENT_COLUMN_EVIDENCE = "no {term} column in the mapped occurrence table"
BLANK_COLUMN_EVIDENCE = "{term} column blank on every row of the mapped occurrence table"

QPCR_BLOCK_TERMS = (
    "probeReporter",
    "probeQuencher",
    "ampliconSize",
    "thresholdQuantificationCycle",
    "baselineValue",
    "pcr_primer_lod",
    "pcr_primer_loq",
)
METABARCODING_NOT_APPLICABLE_REASON = "study_design: metabarcoding"


@dataclass(frozen=True)
class TermState:
    term: str
    state: str
    evidence: str


def b1c_terms(term_table: dict) -> list[str]:
    return sorted(name for name, entry in term_table.items() if entry.get("priority_tier"))


def filled_terms(
    proposals: list[map_terms.MappingProposal], table: Table | None = None
) -> dict[str, str]:
    mapped = {
        proposal.target: _mapping_evidence(proposal)
        for proposal in proposals
        if proposal.target not in ("", "dynamicProperties")
    }
    if table is None:
        return mapped
    terms = [term for term in table.columns if term != "dynamicProperties"]
    if not terms:
        return {}
    defaults = map_terms.DEFAULTED_TERMS
    counts = table.one(
        "SELECT "
        + ", ".join(
            f"count(*) FILTER (WHERE {table.text(term)} <> ''), "
            f"count(*) FILTER (WHERE {table.text(term)} NOT IN ('', {literal(defaults.get(term, ''))}))"
            for term in terms
        )
        + f" FROM {table.name}"
    )
    observed: dict[str, str] = {}
    for i, term in enumerate(terms):
        filled, not_default = counts[2 * i], counts[2 * i + 1]
        if not filled:
            continue
        default_only = term in defaults and not not_default
        observed[term] = mapped.get(term) or (
            f"default:{defaults[term]}" if default_only else MAPPED_TABLE_EVIDENCE
        )
    return observed


def _mapping_evidence(proposal: map_terms.MappingProposal) -> str:
    if map_terms.is_constant_row(proposal.source_column):
        return f"constant:{proposal.provenance}"
    return f"term_mapping.tsv:{proposal.source_column}"


def archive_requires(term: str, term_table: dict) -> bool:
    return term_table.get(term, {}).get("tier") == "required"


def classify_term_states(
    terms: list[str],
    *,
    filled_terms: dict[str, str] | None = None,
    ask_terms: dict[str, str] | None = None,
    impossible_terms: dict[str, str] | None = None,
    not_applicable_terms: dict[str, str] | None = None,
    assay_type: str = "metabarcoding",
    mapped_columns: list[str] | None = None,
) -> list[TermState]:
    filled_terms = filled_terms or {}
    ask_terms = dict(ask_terms or {})
    impossible_terms = impossible_terms or {}
    not_applicable_terms = dict(not_applicable_terms or {})

    if assay_type == "metabarcoding":
        for term in QPCR_BLOCK_TERMS:
            already_classified = (
                term in filled_terms or term in ask_terms or term in impossible_terms
            )
            if not already_classified and term not in not_applicable_terms:
                not_applicable_terms[term] = METABARCODING_NOT_APPLICABLE_REASON

    if mapped_columns is not None:
        header = set(mapped_columns)
        for term in terms:
            if (
                term in filled_terms
                or term in ask_terms
                or term in impossible_terms
                or term in not_applicable_terms
            ):
                continue
            evidence = BLANK_COLUMN_EVIDENCE if term in header else ABSENT_COLUMN_EVIDENCE
            ask_terms[term] = evidence.format(term=term)

    states = []
    for term in terms:
        if term in filled_terms:
            states.append(TermState(term, "Filled", filled_terms[term]))
        elif term in not_applicable_terms:
            states.append(TermState(term, "Not-applicable", not_applicable_terms[term]))
        elif term in impossible_terms:
            states.append(TermState(term, "Impossible", impossible_terms[term]))
        elif term in ask_terms:
            states.append(TermState(term, "Ask", ask_terms[term]))
        else:
            states.append(TermState(term, "", ""))
    return states


def check_every_term_has_a_state(states: list[TermState]) -> tuple[bool, str]:
    missing = [s.term for s in states if s.state == ""]
    if missing:
        return False, f"no state for: {', '.join(missing)}"
    return True, ""


def write_term_states_tsv(states: list[TermState], out_path) -> None:
    rows = [{"term": s.term, "state": s.state, "evidence": s.evidence} for s in states]
    write_tsv(rows, out_path, columns=["term", "state", "evidence"])


def _refuse_excusing_required_terms(
    excused: dict[str, str], term_table: dict, *, judgment: str
) -> dict[str, str]:
    required = sorted(term for term in excused if archive_requires(term, term_table))
    if required:
        raise TermSpecError(
            f"term_states.{judgment} cannot excuse {', '.join(required)}, which every archive "
            "must include"
        )
    return excused


def state_terms(
    term_table: dict,
    proposals: list[map_terms.MappingProposal],
    table: Table | None = None,
    *,
    assay_type: str = "metabarcoding",
    not_applicable: dict[str, str] | None = None,
    ask: dict[str, str] | None = None,
    impossible: dict[str, str] | None = None,
) -> tuple[list[TermState], FindingsLog]:
    states = classify_term_states(
        b1c_terms(term_table),
        filled_terms=filled_terms(proposals, table),
        ask_terms=ask,
        impossible_terms=_refuse_excusing_required_terms(
            impossible or {}, term_table, judgment="impossible"
        ),
        not_applicable_terms=_refuse_excusing_required_terms(
            not_applicable or {}, term_table, judgment="not_applicable"
        ),
        assay_type=assay_type,
        mapped_columns=sorted(table.columns) if table is not None else None,
    )
    log = FindingsLog()
    passed, reason = check_every_term_has_a_state(states)
    if not passed:
        unstated = sum(1 for state in states if state.state == NO_STATE)
        log.add("TERM_STATE_MISSING", reason, count=unstated)
    return states, log
