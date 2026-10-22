from __future__ import annotations

from dataclasses import dataclass


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
    evidence: str


def b1c_terms(term_table: dict) -> list[str]:


def classify_term_states(
    terms: list[str],
    *,
    filled_terms: dict[str, str] | None = None,
    ask_terms: dict[str, str] | None = None,
    impossible_terms: dict[str, str] | None = None,
    not_applicable_terms: dict[str, str] | None = None,
    assay_type: str = "metabarcoding",
) -> list[TermState]:
    filled_terms = filled_terms or {}
    impossible_terms = impossible_terms or {}
    not_applicable_terms = dict(not_applicable_terms or {})

    if assay_type == "metabarcoding":
        for term in QPCR_BLOCK_TERMS:
            already_classified = (
                term in filled_terms or term in ask_terms or term in impossible_terms
            )
            if not already_classified and term not in not_applicable_terms:
                not_applicable_terms[term] = METABARCODING_NOT_APPLICABLE_REASON

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
