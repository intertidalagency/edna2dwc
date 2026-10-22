from __future__ import annotations

from collections.abc import Iterator
import csv
import gzip
import io
from pathlib import Path
from typing import IO

FIELD_SIZE_LIMIT = 10_000_000

SAMPLE_BYTES = 65536

ENCODING = "utf-8-sig"

GZIP_SUFFIX = ".gz"

DELIMITER_CANDIDATES = "\t,;|"
csv.field_size_limit(FIELD_SIZE_LIMIT)


def open_text(path: Path, encoding: str = ENCODING) -> IO[str]:
    if path.suffix.lower() == GZIP_SUFFIX:
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding=encoding, newline="")
    return path.open(encoding=encoding, newline="")


def detect_delimiter(sample: str) -> str:
    header = sample.splitlines()[0] if sample else ""
    widths = {d: len(next(csv.reader([header], delimiter=d), [])) for d in DELIMITER_CANDIDATES}
    return max(widths, key=widths.__getitem__)


def detect_file_delimiter(path: Path) -> str:
    with open_text(path) as f:
        sample = f.read(SAMPLE_BYTES)
    return detect_delimiter(sample)


def read_rows(path: Path, delimiter: str | None = None) -> Iterator[dict[str, str]]:
    if delimiter is None:
        delimiter = detect_file_delimiter(path)
    with open_text(path) as f:
        yield from csv.DictReader(f, delimiter=delimiter)


def read_header(path: Path, delimiter: str | None = None) -> list[str]:
    if delimiter is None:
        delimiter = detect_file_delimiter(path)
    with open_text(path) as f:
        reader = csv.reader(f, delimiter=delimiter)
        return next(reader, [])


_FORBIDDEN_FIELD_CHARS = ("\t", "\r", "\n")


def _sanitize_field(value: str) -> str:
    for ch in _FORBIDDEN_FIELD_CHARS:
        if ch in value:
            value = value.replace(ch, " ")
    return value


def ensure_parent_dir(out_path: Path) -> None:
    parent = out_path.parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def write_tsv(
    rows: list[dict[str, str]], out_path: Path, *, columns: list[str] | None = None
) -> None:
    if columns is None:
        columns = sorted_columns(rows)
        if not columns:
            ensure_parent_dir(out_path)
            out_path.write_text("", encoding="utf-8")
            return
    ensure_parent_dir(out_path)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(_sanitize_field(c) for c in columns) + "\n")
        f.writelines(
            "\t".join(_sanitize_field(str(row.get(c, ""))) for c in columns) + "\n" for row in rows
        )


def sorted_columns(rows: list[dict[str, str]]) -> list[str]:
    return sorted({k for row in rows for k in row})


class NotTabSeparatedError(ValueError):
    pass


def require_tab_separated(path: Path) -> None:
    with open_text(path) as f:
        header = f.readline()
    if "\t" in header:
        return
    other = next((d for d in DELIMITER_CANDIDATES if d in header), None)
    if other is not None:
        raise NotTabSeparatedError(
            f"{path} is separated by {other!r}, but the intermediate table must be "
            "tab-separated. Write it with to_csv(path, sep='\\t', index=False) in the "
            "reader script."
        )


def read_tab_separated_rows(path: Path) -> Iterator[dict[str, str]]:
    require_tab_separated(path)
    return read_rows(path, delimiter="\t")


def read_tab_separated_header(path: Path) -> list[str]:
    require_tab_separated(path)
    return read_header(path, delimiter="\t")
