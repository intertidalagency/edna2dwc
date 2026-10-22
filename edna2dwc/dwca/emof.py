from __future__ import annotations

from dataclasses import dataclass
import re


DYNAMIC_PROPERTIES_COLUMN = "dynamicProperties"
NUMERIC_SELECTION_THRESHOLD = 0.95

_HEADER_UNIT_SPLIT_RE = re.compile(
)


@dataclass(frozen=True)
class MeasurementAlias:
    patterns: tuple[str, ...]
    measurement_type: str
    measurement_type_id: str = ""


_P01 = "http://vocab.nerc.ac.uk/collection/P01/current/{}/"
_P06 = "http://vocab.nerc.ac.uk/collection/P06/current/{}/"

ALIAS_TABLE: tuple[MeasurementAlias, ...] = (
    MeasurementAlias(
    ),
)


def _normalize_for_matching(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def alias_for(header: str) -> MeasurementAlias | None:
    base, _ = split_header_unit(header)


def split_header_unit(header: str) -> tuple[str, str | None]:
    match = _HEADER_UNIT_SPLIT_RE.match(header)
    if not match:
        return header, None
    return match.group("base"), match.group("us1") or match.group("us2")










