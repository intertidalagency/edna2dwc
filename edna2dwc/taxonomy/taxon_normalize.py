from __future__ import annotations

import re

_PARENTHESIZED_RE = re.compile(r"\([^)]*\)")
_UNDERSCORE_JOINED_LATIN_NAME_RE = re.compile(r"(?:Candidatus_)?[A-Z][a-z-]*(?:_[a-z][a-z-]*)*")
_LATIN_NAME_RE = re.compile(
    r"(?:Candidatus\s+)?\S+(?:\s+(?:(?:subsp|ssp|var|f)\.\s+)?[a-z][a-z-]*(?!\S))*"
)
_YEAR_RE = re.compile(r"\d{4}[a-z]?")
_ENDS_A_NAME = {"sp.", "sp", "spp.", "spp"}
_QUALIFIERS = {"cf.", "cf", "aff.", "aff", "other", "others"}
_HYBRID_SIGNS = {"x", "X"}
_AUTHORITY_COMMA = r",(?=[^,/|]*\b\d{4}[a-z]?\b)"
COMPOUND_SEPARATOR_RE = re.compile(rf"\s+or\s+|/|\||(?!{_AUTHORITY_COMMA}),")
_COMPOUND_PARTS_RE = re.compile(f"({COMPOUND_SEPARATOR_RE.pattern})")
_NCBI_TAXID_RE = re.compile(r"(?:NCBI:)?(?:txid)?0*(\d+)(?:\.0*)?", re.IGNORECASE)
NCBI_TAXIDS_NAMING_NO_TAXON = {"0": "no taxon", "1": "the root", "131567": "cellular organisms"}
RANK_WORDS = frozenset(
    {
        "domain",
        "superkingdom",
        "kingdom",
        "subkingdom",
        "superphylum",
        "phylum",
        "subphylum",
        "division",
        "superclass",
        "class",
        "subclass",
        "infraclass",
        "superorder",
        "order",
        "suborder",
        "infraorder",
        "superfamily",
        "family",
        "subfamily",
        "tribe",
        "subtribe",
        "genus",
        "subgenus",
        "species",
        "subspecies",
        "variety",
        "forma",
    }
)


def is_rank_word(name: str) -> bool:
    return name.strip().removesuffix(":").strip().casefold() in RANK_WORDS


def _before_sp(tokens: list[str]) -> list[str]:
    ends = [index for index, token in enumerate(tokens) if token.casefold() in _ENDS_A_NAME]
    return tokens[: ends[0]] if ends else tokens


def _is_hybrid_formula(tokens: list[str]) -> bool:
    return any(token in _HYBRID_SIGNS or "×" in token for token in tokens)


def _split_authority(part: str) -> tuple[str, str, str]:
    match = re.search(_AUTHORITY_COMMA, part)
    if match is None:
        return part, "", ""
    return part[: match.start()], ",", part[match.end() :]


def _latin_name(part: str) -> str:
    if "_" in part:
        joined = _UNDERSCORE_JOINED_LATIN_NAME_RE.fullmatch(part.strip())
        return joined[0].replace("_", " ") if joined else ""
    head, comma, _ = _split_authority(_PARENTHESIZED_RE.sub(" ", part))
    tokens = [t for t in _before_sp(head.split()) if t.casefold() not in _QUALIFIERS]
    text = " ".join(tokens)
    if _is_hybrid_formula(tokens):
        return text
    latin = _LATIN_NAME_RE.match(text)
    if latin is None:
        return text
    name = latin[0]
    rest = text[latin.end() :].split()
    cited = comma or (rest and _YEAR_RE.fullmatch(rest[-1]))
    has_epithet = len(name.split()) > (2 if name.startswith("Candidatus") else 1)
    return name if has_epithet or cited else text


def normalize_name(name: str) -> str:
    parts = _COMPOUND_PARTS_RE.split(name)
    names = [_latin_name(part) for part in parts[::2]]
    separators = [_glue(separator) for separator in parts[1::2]]
    joined = ""
    for index, part in enumerate(names):
        if not part:
            continue
        if joined:
            joined += separators[index - 1]
        joined += part
    return " ".join(joined.split())


def _glue(separator: str) -> str:
    stripped = separator.strip()
    if stripped.isalpha():
        return f" {stripped} "
    return ", " if stripped == "," else stripped


def ncbi_taxid_digits(value: str) -> str | None:
    match = _NCBI_TAXID_RE.fullmatch(value.strip())
    return match[1] if match else None
