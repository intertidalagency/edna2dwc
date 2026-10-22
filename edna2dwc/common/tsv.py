from __future__ import annotations

from collections.abc import Iterator
import csv
from pathlib import Path

FIELD_SIZE_LIMIT = 10_000_000

csv.field_size_limit(FIELD_SIZE_LIMIT)






def read_rows(path: Path, delimiter: str | None = None) -> Iterator[dict[str, str]]:
    if delimiter is None:
        yield from csv.DictReader(f, delimiter=delimiter)


def read_header(path: Path, delimiter: str | None = None) -> list[str]:
    if delimiter is None:
        reader = csv.reader(f, delimiter=delimiter)
        return next(reader, [])




        if ch in value:
            value = value.replace(ch, " ")
    return value


def write_tsv(
    rows: list[dict[str, str]], out_path: Path, *, columns: list[str] | None = None
) -> None:
    if columns is None:
        if not columns:
            out_path.write_text("", encoding="utf-8")
            return
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(_sanitize_field(c) for c in columns) + "\n")
        f.writelines(
            "\t".join(_sanitize_field(str(row.get(c, ""))) for c in columns) + "\n" for row in rows
        )


