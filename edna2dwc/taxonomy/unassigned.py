from __future__ import annotations

import re

PLACEHOLDER_TAXA = frozenset({"biota incertae sedis", "biota"})

NO_ASSIGNMENT_SENTINELS = frozenset(
    {
        "*",
        "na",
        "n/a",
        "other",
        "others",
        "none",
        "null",
        "no hit",
        "no_hit",
        "no hits",
        "no match",
        "no_match",
        "root",
        "cellular organisms",
        "environmental samples",
    }
)

_SENTINEL_PATTERN_RE = re.compile(
    r"""^(
          incertae\ sedis
        | no[\ _]?(hit|hits|match|identification)
        | (unassigned|unclassified|uncultured|unidentified|unknown)([\ _].*)?
        | (.*[\ _])?metagenome
    )$""",
    re.IGNORECASE | re.VERBOSE,
)


def is_placeholder_taxon(name: str) -> bool:
    return name.strip().casefold() in PLACEHOLDER_TAXA


def is_no_assignment(value: str) -> bool:
    trimmed = value.strip()
    if not trimmed:
        return False
    return trimmed.casefold() in NO_ASSIGNMENT_SENTINELS or bool(
        _SENTINEL_PATTERN_RE.match(trimmed)
    )
