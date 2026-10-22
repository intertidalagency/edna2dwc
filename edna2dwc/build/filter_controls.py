from __future__ import annotations

import re


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
)


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
    is_positive_control: bool
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


    return SampleClassification(
        sample_id=sample_id,
        is_control=False,
        is_ambiguous=False,
        is_positive_control=False,
        basis="none",
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
        matched_keyword=row.get("matched_keyword", ""),
    )




    )
        findings.add(
            "CONTROL_EXCLUDED",
        )
