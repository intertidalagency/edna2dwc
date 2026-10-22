from __future__ import annotations

from collections import Counter
import csv
from pathlib import Path

from edna2dwc.common.tsv import DELIMITER_CANDIDATES, GZIP_SUFFIX

DELIMITED_SUFFIXES = frozenset({".csv", ".tsv", ".tab"})

TEXT_BY_CONTENT_SUFFIXES = frozenset({".txt"})

FASTA_SUFFIXES = frozenset({".fasta", ".fa", ".fna", ".fas"})

FIELD_COUNT_AGREEMENT = 0.8


def data_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    inner = Path(path.stem).suffix.lower()
    if (
        suffix == GZIP_SUFFIX
        and inner in DELIMITED_SUFFIXES | TEXT_BY_CONTENT_SUFFIXES | FASTA_SUFFIXES
    ):
        return inner
    return suffix


def looks_delimited(sample: str) -> bool:
    rows = _whole_rows(sample)
    return any(_splits_evenly(rows, delimiter) for delimiter in DELIMITER_CANDIDATES)


def _whole_rows(sample: str) -> list[str]:
    lines = [line for line in sample.splitlines() if line.strip()]
    if len(lines) > 1 and not sample.endswith("\n"):
        return lines[:-1]
    return lines


def _splits_evenly(rows: list[str], delimiter: str) -> bool:
    field_counts = Counter(len(row) for row in csv.reader(rows, delimiter=delimiter))
    if not field_counts:
        return False
    fields, agreeing = field_counts.most_common(1)[0]
    return fields > 1 and agreeing >= FIELD_COUNT_AGREEMENT * field_counts.total()
