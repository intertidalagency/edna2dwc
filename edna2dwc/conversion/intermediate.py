from __future__ import annotations

from pathlib import Path


REQUIRED_COLUMNS = ("sampleID", "featureID", "count")
TAXONOMY_COLUMN = "taxonomy"




def validate_intermediate(path: Path) -> FindingsLog:
    log = FindingsLog()

    seen_names: set[str] = set()
    duplicate_names: set[str] = set()
    for name in header:
        if name in seen_names:
            duplicate_names.add(name)
        seen_names.add(name)
    if duplicate_names:
        log.add(
            "CONTRACT_INVALID",
            f"Duplicate header name(s): {', '.join(sorted(duplicate_names))}",
        )

    for name in REQUIRED_COLUMNS:
        if name not in header:
            log.add("CONTRACT_COLUMN_MISSING", f"Required column {name!r} is missing")

        log.add(
            "CONTRACT_COLUMN_MISSING",
        )

    can_check_rows = not duplicate_names and all(name in header for name in REQUIRED_COLUMNS)


