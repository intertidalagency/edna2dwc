from __future__ import annotations

from dataclasses import dataclass, field, replace
import re

import duckdb

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import ROW, Table, from_rows, internal

CONTROL_KEYWORDS = (
    "blank",
    "negative control",
    "negative-control",
    "neg control",
    "ntc",
    "no template control",
    "extraction blank",
    "extraction control",
    "field blank",
    "filter blank",
    "lab blank",
    "pcr blank",
    "pcr control",
    "pcr negative",
    "pcr neg",
    "neg pcr",
    "negpcr",
    "positive control",
    "pos control",
    "mock",
    "mock community",
    "zymo",
    "control",
    "blk",
    "nc",
    "ec",
    "kitome",
    "neg",
)

ANSWER_BASIS = "answer"
SAMPLE_ID_BASIS = "sample_id_string_match"

AMBIGUOUS_KEYWORDS = frozenset({"blk", "nc", "ec", "ntc", "control", "mock", "neg"})

POSITIVE_CONTROL_KEYWORDS = frozenset(
    {"positive control", "pos control", "mock", "mock community", "zymo"}
)

_TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")
_TRANSITION_RE = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])"
)


def tokenize(value: str) -> list[str]:
    tokens: list[str] = []
    for chunk in _TOKEN_SPLIT_RE.split(value):
        if chunk:
            tokens.extend(t for t in _TRANSITION_RE.split(chunk) if t)
    return tokens


_KEYWORD_TOKENS = sorted(
    (tuple(tok.casefold() for tok in tokenize(kw)) for kw in CONTROL_KEYWORDS),
    key=len,
    reverse=True,
)


@dataclass(frozen=True)
class KeywordMatch:
    keyword: str
    is_ambiguous_keyword: bool
    is_positive_control_keyword: bool


def match_keywords(value: str) -> list[KeywordMatch]:
    tokens = [t.casefold() for t in tokenize(value)]
    matches = []
    for kw_tokens in _KEYWORD_TOKENS:
        n = len(kw_tokens)
        for i in range(len(tokens) - n + 1):
            if tuple(tokens[i : i + n]) == kw_tokens:
                keyword = " ".join(kw_tokens)
                matches.append(
                    KeywordMatch(
                        keyword=keyword,
                        is_ambiguous_keyword=keyword in AMBIGUOUS_KEYWORDS,
                        is_positive_control_keyword=keyword in POSITIVE_CONTROL_KEYWORDS,
                    )
                )
                break
    return matches


_METADATA_CONTROL_VALUES = frozenset(
    {
        "control",
        "blank",
        "negative",
        "negative control",
        "positive",
        "positive control",
        "mock",
        "mock community",
        "ntc",
        "zymo",
    }
)
_METADATA_POSITIVE_VALUES = frozenset(
    {"positive", "positive control", "mock", "mock community", "zymo"}
)


@dataclass(frozen=True)
class SampleClassification:
    sample_id: str
    is_control: bool
    is_ambiguous: bool
    is_positive_control: bool
    basis: str
    matched_keyword: str = ""


def classify_sample(
    sample_id: str,
    *,
    metadata_type: str | None = None,
    occurrence_type: str | None = None,
) -> SampleClassification:
    for basis, raw_type in (
        ("sample_metadata", metadata_type),
        ("occurrence_type", occurrence_type),
    ):
        if not raw_type:
            continue
        normalized = raw_type.strip().casefold()
        if normalized in _METADATA_CONTROL_VALUES:
            return SampleClassification(
                sample_id=sample_id,
                is_control=True,
                is_ambiguous=False,
                is_positive_control=normalized in _METADATA_POSITIVE_VALUES,
                basis=basis,
                matched_keyword=normalized,
            )
        if matches := match_keywords(raw_type):
            return _keyword_classification(sample_id, matches, basis)

    if matches := match_keywords(sample_id):
        return _keyword_classification(sample_id, matches, SAMPLE_ID_BASIS)

    return SampleClassification(
        sample_id=sample_id,
        is_control=False,
        is_ambiguous=False,
        is_positive_control=False,
        basis="none",
    )


def _keyword_classification(
    sample_id: str, matches: list[KeywordMatch], basis: str
) -> SampleClassification:
    strong = [m for m in matches if not m.is_ambiguous_keyword]
    chosen = strong[0] if strong else matches[0]
    return SampleClassification(
        sample_id=sample_id,
        is_control=True,
        is_ambiguous=not strong,
        is_positive_control=any(m.is_positive_control_keyword for m in matches),
        basis=basis,
        matched_keyword=chosen.keyword,
    )


def classification_from_report_row(row: dict[str, str]) -> SampleClassification:
    normalized = row.get("matched_keyword", "").strip().casefold()
    return SampleClassification(
        sample_id=row.get("sampleID", ""),
        is_control=row.get("type") == "control",
        is_ambiguous=row.get("action") == "ambiguous",
        is_positive_control=(
            normalized in POSITIVE_CONTROL_KEYWORDS or normalized in _METADATA_POSITIVE_VALUES
        ),
        basis=row.get("basis", ""),
        matched_keyword=row.get("matched_keyword", ""),
    )


SAMPLE_ID_COLUMNS = ("sampleID", "sample_id")


def apply_control_answer(
    classification: SampleClassification, answer: str
) -> SampleClassification:
    is_control = answer == "control"
    return replace(
        classification,
        is_control=is_control,
        is_ambiguous=False,
        is_positive_control=is_control and classification.is_positive_control,
        basis=ANSWER_BASIS,
    )


@dataclass(frozen=True)
class SampleSeen:
    sample_id: str
    occurrence_type: str
    row_count: int


def samples_seen(table: Table, occurrence_type_col: str | None) -> list[SampleSeen]:
    occurrence_type = table.text(occurrence_type_col) if occurrence_type_col else "''"
    sample_id = table.text("sampleID")
    return [
        SampleSeen(*seen)
        for seen in table.rows(
            f"SELECT {sample_id}, arg_min({occurrence_type}, {ROW}), count(*) "
            f"FROM {table.name} GROUP BY 1 ORDER BY min({ROW})"
        )
    ]


def resolve_classifications(
    samples: list[SampleSeen],
    *,
    sample_metadata_by_id: dict[str, str] | None = None,
    control_answers: dict[str, str] | None = None,
) -> dict[str, SampleClassification]:
    sample_metadata_by_id = sample_metadata_by_id or {}
    control_answers = control_answers or {}
    classifications: dict[str, SampleClassification] = {}
    for sample in samples:
        classification = classify_sample(
            sample.sample_id,
            metadata_type=sample_metadata_by_id.get(sample.sample_id),
            occurrence_type=sample.occurrence_type,
        )
        if sample.sample_id in control_answers:
            classification = apply_control_answer(
                classification, control_answers[sample.sample_id]
            )
        classifications[sample.sample_id] = classification
    return classifications


@dataclass
class SampleRoster:
    report_rows: list[dict[str, str]]
    findings: FindingsLog = field(default_factory=FindingsLog)


def build_roster(
    samples: list[SampleSeen], classifications: dict[str, SampleClassification]
) -> SampleRoster:
    findings = FindingsLog()
    report_rows: list[dict[str, str]] = []
    row_counts = {sample.sample_id: sample.row_count for sample in samples}
    for sample_id, classification in classifications.items():
        exclude = classification.is_control and not classification.is_ambiguous
        report_rows.append(
            {
                "sampleID": sample_id,
                "type": "control" if classification.is_control else "sample",
                "basis": classification.basis,
                "matched_keyword": classification.matched_keyword,
                "action": "excluded"
                if exclude
                else ("ambiguous" if classification.is_ambiguous else "kept"),
                "row_count": str(row_counts[sample_id]),
            }
        )
        if not classification.is_ambiguous:
            continue
        findings.add(
            "CONTROL_AMBIGUOUS",
            f"Sample {sample_id!r}: uncorroborated keyword match "
            f"{classification.matched_keyword!r}, so the sample was kept until answers.yaml says control or sample",
        )
    return SampleRoster(report_rows=report_rows, findings=findings)


SAMPLE = internal("sampleID")
KEYWORD = internal("keyword")
EXCLUDED = internal("excluded")
POSITIVE = internal("positive")
SEEDS_LEAKAGE = internal("seeds_leakage")


def control_samples(con: duckdb.DuckDBPyConnection, roster: list[dict[str, str]]) -> Table:
    classifications = [classification_from_report_row(row) for row in roster]
    return from_rows(
        con,
        "control_samples",
        {
            SAMPLE: "VARCHAR",
            KEYWORD: "VARCHAR",
            EXCLUDED: "BOOLEAN",
            POSITIVE: "BOOLEAN",
            SEEDS_LEAKAGE: "BOOLEAN",
        },
        [
            (
                c.sample_id,
                c.matched_keyword,
                c.is_control and not c.is_ambiguous,
                c.is_positive_control,
                c.is_control and c.is_positive_control,
            )
            for c in classifications
        ],
    )


def control_findings(table: Table, controls: Table) -> FindingsLog:
    findings = FindingsLog()
    sample, name = table.text("sampleID", "row"), table.text("scientificName", "row")
    joined = f"{table.name} AS row JOIN {controls.name} ON {sample} = {controls.name}.{SAMPLE}"
    leaks = table.rows(
        f"SELECT {name}, {sample} FROM {joined} "
        f"WHERE NOT {EXCLUDED} AND NOT {POSITIVE} AND {name} IN "
        f"(SELECT {name} FROM {joined} WHERE {SEEDS_LEAKAGE} AND {name} <> '') "
        f"ORDER BY row.{ROW}"
    )
    for scientific_name, sample_id in leaks:
        findings.add(
            "CONTROL_TAXON_LEAKAGE",
            f"{scientific_name!r} (a positive-control organism) found in "
            f"non-control sample {sample_id!r}",
        )
    (excluded_samples,) = controls.one(f"SELECT count(*) FROM {controls.name} WHERE {EXCLUDED}")
    if excluded_samples:
        findings.add(
            "CONTROL_EXCLUDED",
            f"{excluded_samples} control/blank sample(s) excluded",
            count=excluded_samples,
        )
    return findings
