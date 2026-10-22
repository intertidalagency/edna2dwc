from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
from pathlib import Path



_MASK_64 = (1 << 64) - 1

DEFAULT_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Fingerprint:
    n_rows: int
    n_distinct_ids: int
    xor_hash: int
    total: float

    @property
    def is_blank(self) -> bool:
        return self.n_rows == 0 or self.total == 0


def _id_hash(id_value: str) -> int:
    digest = hashlib.sha256(id_value.encode("utf-8")).hexdigest()
    return int(digest, 16) & _MASK_64


def _has_header(path: Path) -> bool:
    if len(sample_lines) < 2:
        return False
    try:
        return csv.Sniffer().has_header("".join(sample_lines))
    except csv.Error:
        return True


def fingerprint_file(path: Path) -> Fingerprint:
    skip_header = _has_header(path)
    n_rows = 0
    total = 0.0
    xor_hash = 0
    seen_ids: set[str] = set()
        for i, line in enumerate(f):
            row = line.rstrip("\n").split(delimiter)
            if not row or not row[0]:
                continue
            if i == 0 and skip_header:
                continue
            n_rows += 1
            id_value = row[0]
            if id_value not in seen_ids:
                seen_ids.add(id_value)
                xor_hash ^= _id_hash(id_value)
            for cell in row[1:]:
                try:
                    total += float(cell)
                except ValueError:
                    continue
    return Fingerprint(n_rows=n_rows, n_distinct_ids=len(seen_ids), xor_hash=xor_hash, total=total)


def verdict(a: Fingerprint, b: Fingerprint, *, tolerance: float = DEFAULT_TOLERANCE) -> str:
    if a.is_blank or b.is_blank:
        return "blank"
    ids_equal = a.n_distinct_ids == b.n_distinct_ids and a.xor_hash == b.xor_hash
    totals_equal = abs(a.total - b.total) <= tolerance * max(abs(a.total), abs(b.total), 1)
    counts_equal = a.n_rows == b.n_rows
    if ids_equal and counts_equal and totals_equal:
        return "likely redundant"
    if ids_equal and not totals_equal:
        return "raw vs. normalized, not redundant"
    if not ids_equal and totals_equal:
        return "coincidental"
    return "distinct"


@dataclass
class RedundancyReport:
    fingerprints: dict[str, Fingerprint]
    failures: dict[str, str]
    verdicts: dict[tuple[str, str], str]

    def to_dict(self) -> dict:
        return {
            "fingerprints": {
                path: {
                    "n_rows": fp.n_rows,
                    "n_distinct_ids": fp.n_distinct_ids,
                    "xor_hash": fp.xor_hash,
                    "total": fp.total,
                }
                for path, fp in self.fingerprints.items()
            },
            "failures": self.failures,
            "verdicts": {f"{a} vs {b}": v for (a, b), v in self.verdicts.items()},
        }


def detect_redundant_paths(
    paths: list[Path], *, tolerance: float = DEFAULT_TOLERANCE
) -> RedundancyReport:
    fingerprints: dict[str, Fingerprint] = {}
    failures: dict[str, str] = {}
    for path in paths:
        try:
            fingerprints[str(path)] = fingerprint_file(path)
        except (OSError, UnicodeDecodeError) as e:
            failures[str(path)] = str(e)

    if paths and not fingerprints:
        raise ValueError(
            f"could not fingerprint any of {len(paths)} file(s): "
            f"{'; '.join(f'{p}: {msg}' for p, msg in failures.items())}"
        )

    verdicts: dict[tuple[str, str], str] = {}
    names = list(fingerprints)
    for i, a_name in enumerate(names):
        for b_name in names[i + 1 :]:
            verdicts[(a_name, b_name)] = verdict(
                fingerprints[a_name], fingerprints[b_name], tolerance=tolerance
            )
    return RedundancyReport(fingerprints=fingerprints, failures=failures, verdicts=verdicts)
