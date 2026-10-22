from __future__ import annotations

from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import errno
from functools import cached_property
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import duckdb

from edna2dwc.common.tsv import (
    detect_file_delimiter,
    ensure_parent_dir,
    read_header,
    read_tab_separated_header,
)

MEMORY_LIMIT_ENV = "EDNA2DWC_MEMORY_LIMIT"
SHARE_OF_MEMORY = 0.5
CGROUP_LIMITS = (
    Path("/sys/fs/cgroup/memory.max"),
    Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
)
COLUMNS_PER_READ = 500
ROW = '"^_row"'
LINE = '"^_line"'
WRITE_BATCH_BYTES = 16 << 20
ROW_GROUP_ROWS = 16384
LOOKUP_BATCH_ROWS = 50_000
BATCH_ROW = '"^_batch_row"'
_ESCAPED = "^"


def _encoded(name: str) -> str:
    return "".join(f"{_ESCAPED}{ch}" if ch.isupper() or ch == _ESCAPED else ch for ch in name)


def column(name: str) -> str:
    return name if name.startswith('"^_') else '"' + _encoded(name).replace('"', '""') + '"'


def _unquoted(identifier: str) -> str:
    return identifier[1:-1].replace('""', '"')


def internal(name: str) -> str:
    return f'"^_{name}"'


def _display(physical: str) -> str:
    chars = iter(physical)
    return "".join(next(chars) if ch == _ESCAPED else ch for ch in chars)


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def is_json_object(expression: str) -> str:
    keys = f"json_keys({expression})"
    return (
        f"CASE WHEN json_valid({expression}) THEN json_type({expression}) = 'OBJECT' "
        f"AND len({keys}) = len(list_distinct({keys})) ELSE FALSE END"
    )


def literals(values: Sequence[str]) -> str:
    return "(" + ", ".join(literal(value) for value in values) + ")" if values else "(NULL)"


def usable_memory() -> int:
    limits = [_machine_memory()]
    for path in CGROUP_LIMITS:
        if path.is_file() and (text := path.read_text(encoding="utf-8").strip()).isdigit():
            limits.append(int(text))
    return min(limits)


def _machine_memory() -> int:
    if sys.platform != "win32":
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("load", ctypes.c_ulong),
            ("sizes", ctypes.c_ulonglong * 7),
        ]

    status = MemoryStatus(length=ctypes.sizeof(MemoryStatus))
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.sizes[0]


def memory_limit() -> str:
    return os.environ.get(MEMORY_LIMIT_ENV) or f"{int(usable_memory() * SHARE_OF_MEMORY) >> 20}MiB"


def memory_limit_source() -> str:
    if os.environ.get(MEMORY_LIMIT_ENV):
        return f"set by {MEMORY_LIMIT_ENV}"
    return f"{SHARE_OF_MEMORY:.0%} of the {in_gib(usable_memory())} this process can use"


def spill_dir() -> Path:
    return Path(tempfile.gettempdir())


def spill_free_bytes() -> int:
    return shutil.disk_usage(spill_dir()).free


def in_gib(n_bytes: int) -> str:
    return f"{n_bytes / (1 << 30):.1f} GiB"


class ResourceLimitError(Exception):
    pass


def _out_of_memory() -> str:
    return (
        f"DuckDB ran out of memory within its limit of {memory_limit()}, {memory_limit_source()}, "
        f"with {in_gib(spill_free_bytes())} free in {spill_dir()} to spill to. Raise "
        f"{MEMORY_LIMIT_ENV}, such as {MEMORY_LIMIT_ENV}=8GB, if the machine has more memory"
    )


def _out_of_disk() -> str:
    return (
        f"The disk under {spill_dir()} is full, with {in_gib(spill_free_bytes())} free. DuckDB "
        f"spills there whatever doesn't fit in its memory limit of {memory_limit()}, "
        f"{memory_limit_source()}. Free space there, point TMPDIR at a larger disk, or raise "
        f"{MEMORY_LIMIT_ENV} if the machine has more memory"
    )


def _is_disk_full(error: Exception) -> bool:
    return getattr(error, "errno", None) == errno.ENOSPC or any(
        sign in str(error) for sign in ("No space left on device", "max_temp_directory_size")
    )


@contextmanager
def connect() -> Generator[duckdb.DuckDBPyConnection]:
    with tempfile.TemporaryDirectory(prefix="edna2dwc-") as scratch:
        try:
            con = duckdb.connect(
                config={
                    "threads": 4,
                    "preserve_insertion_order": False,
                    "temp_directory": str(Path(scratch) / "spill"),
                    "memory_limit": memory_limit(),
                },
            )
        except (duckdb.ParserException, duckdb.InvalidInputException) as error:
            raise ResourceLimitError(
                f"{MEMORY_LIMIT_ENV}={memory_limit()!r} is not a size. Give one such as 2GB or "
                f"512MB, or unset it to use {SHARE_OF_MEMORY:.0%} of the memory this process can use"
            ) from error
        database = literal(str(Path(scratch) / "build.duckdb"))
        con.execute(f"ATTACH {database} AS build (ROW_GROUP_SIZE {ROW_GROUP_ROWS})")
        con.execute("USE build")
        try:
            yield con
        except (duckdb.OutOfMemoryException, duckdb.IOException, OSError) as error:
            if _is_disk_full(error):
                raise ResourceLimitError(_out_of_disk()) from error
            if isinstance(error, duckdb.OutOfMemoryException):
                raise ResourceLimitError(_out_of_memory()) from error
            raise
        finally:
            con.close()


@contextmanager
def connected(
    con: duckdb.DuckDBPyConnection | None,
) -> Generator[duckdb.DuckDBPyConnection]:
    if con is not None:
        yield con
        return
    with connect() as fresh:
        yield fresh


@dataclass(frozen=True)
class Table:
    con: duckdb.DuckDBPyConnection
    name: str

    @cached_property
    def columns(self) -> list[str]:
        physical = self.con.sql(f"SELECT * FROM {self.name} LIMIT 0").columns
        return [_display(name) for name in physical if not name.startswith("^_")]

    def has(self, name: str) -> bool:
        return name in self.columns

    def holds(self, internal_name: str) -> bool:
        physical = self.con.sql(f"SELECT * FROM {self.name} LIMIT 0").columns
        return _unquoted(internal_name) in physical

    def get(self, name: str, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return f"{prefix}{column(name)}" if self.has(name) else "NULL"

    def text(self, name: str, alias: str = "") -> str:
        return f"coalesce({self.get(name, alias)}, '')" if self.has(name) else "''"

    def rows(self, sql: str, params: Sequence | None = None) -> list[tuple]:
        return self.con.execute(sql, params).fetchall()

    def one(self, sql: str) -> tuple:
        row = self.con.execute(sql).fetchone()
        assert row is not None
        return row

    def count(self, where: str = "TRUE") -> int:
        return self.one(f"SELECT count(*) FROM {self.name} WHERE {where}")[0]

    def first(self, expression: str, where: str, n: int = 5) -> tuple[int, list]:
        return self.one(
            f"SELECT count(*), min_by({expression}, {ROW}, {n}) FROM {self.name} WHERE {where}"
        )

    def view(self, name: str, select: str) -> Table:
        self.con.execute(f"CREATE OR REPLACE VIEW {name} AS {select}")
        return Table(self.con, name)

    def save(self, name: str, select: str) -> Table:
        self.con.execute(f"CREATE OR REPLACE TABLE {name} AS {select}")
        return Table(self.con, name)

    def without(self, *names: str) -> str:
        physical = set(self.con.sql(f"SELECT * FROM {self.name} LIMIT 0").columns)
        dropped = [column(name) for name in names if _unquoted(column(name)) in physical]
        return f"* EXCLUDE ({', '.join(dropped)})" if dropped else "*"

    def star(self, *names: str) -> str:
        return f"{self.name}.{self.without(*names)}"

    def dicts(self, where: str = "TRUE") -> list[dict[str, str]]:
        names = self.columns
        selected = ", ".join(column(name) for name in names) or "NULL"
        found = self.rows(f"SELECT {selected} FROM {self.name} WHERE {where} ORDER BY {ROW}")
        return [
            {name: value for name, value in zip(names, row) if value is not None} for row in found
        ]

    def present(self) -> list[str]:
        if not self.columns:
            return []
        counts = self.one(
            "SELECT "
            + ", ".join(f"count({column(name)}) > 0" for name in self.columns)
            + f" FROM {self.name}"
        )
        return [name for name, set_somewhere in zip(self.columns, counts) if set_somewhere]

    def settled(self, name: str, required: Sequence[str] = (), keep: Sequence[str] = ()) -> Table:
        present = self.present()
        settled = [*(c for c in required if c not in present), *present]
        select = "".join(f", coalesce({self.get(c)}, '') AS {column(c)}" for c in settled)
        return self.save(name, f"SELECT {', '.join([ROW, *keep])}{select} FROM {self.name}")


def from_rows(
    con: duckdb.DuckDBPyConnection,
    name: str,
    columns: Mapping[str, str],
    rows: Sequence[Sequence],
) -> Table:
    lists = [list(values) for values in zip(*rows, strict=True)] or [[] for _ in columns]
    select = ", ".join(
        f"unnest(${i}::{sql_type}[]) AS {column(c)}"
        for i, (c, sql_type) in enumerate(columns.items(), start=1)
    )
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT {select}", lists)
    return Table(con, name)


def lookup(
    table: Table,
    name: str,
    keys: Sequence[str],
    results: Mapping[str, str],
    convert: Callable[..., tuple],
    *,
    keep: Callable[[tuple, tuple], bool] | None = None,
) -> Table:
    key_names = [internal(f"{name}_key{i}") for i in range(len(keys))]
    columns = {**dict.fromkeys(key_names, "VARCHAR"), **results}
    distinct = ", ".join(f"{key} AS {key_name}" for key, key_name in zip(keys, key_names))
    found = table.save(
        f"{name}_distinct",
        f"SELECT row_number() OVER () AS {BATCH_ROW}, * FROM (SELECT DISTINCT {distinct} "
        f"FROM {table.name})",
    )
    looked_up = from_rows(table.con, name, columns, [])
    for start in range(0, found.count(), LOOKUP_BATCH_ROWS):
        batch = found.rows(
            f"SELECT * EXCLUDE ({BATCH_ROW}) FROM {found.name} "
            f"WHERE {BATCH_ROW} > {start} AND {BATCH_ROW} <= {start + LOOKUP_BATCH_ROWS}"
        )
        answers = ((values, convert(*values)) for values in batch)
        converted = from_rows(
            table.con,
            f"{name}_batch",
            columns,
            [
                (*values, *answer)
                for values, answer in answers
                if keep is None or keep(values, answer)
            ],
        )
        table.con.execute(f"INSERT INTO {name} SELECT * FROM {converted.name}")
    return looked_up


def matching(found: Table, keys: Sequence[str]) -> str:
    return " AND ".join(
        f"{expression} = {found.name}.{internal(f'{found.name}_key{i}')}"
        for i, expression in enumerate(keys)
    )


def from_dicts(
    con: duckdb.DuckDBPyConnection, name: str, rows: Sequence[Mapping[str, str]]
) -> Table:
    names = list(dict.fromkeys(key for row in rows for key in row))
    return from_rows(
        con,
        name,
        {ROW: "BIGINT", **{c: "VARCHAR" for c in names}},
        [[i, *(row.get(c) for c in names)] for i, row in enumerate(rows)],
    )


def read_tsv(
    con: duckdb.DuckDBPyConnection, path: Path, name: str, header: Sequence[str] | None = None
) -> Table:
    header = read_tab_separated_header(path) if header is None else header
    return _read_delimited(con, path, name, header, "\t")


def read_delimited(con: duckdb.DuckDBPyConnection, path: Path, name: str) -> Table:
    delimiter = detect_file_delimiter(path)
    return _read_delimited(con, path, name, read_header(path, delimiter), delimiter)


def read_unpivoted(
    con: duckdb.DuckDBPyConnection,
    path: Path,
    name: str,
    ids: Sequence[str],
    into: str,
    value: str,
    where: str,
) -> Table:
    delimiter = detect_file_delimiter(path)
    header = read_header(path, delimiter)
    scan = _scan(path, header, delimiter)
    kept = "".join(f", {column(id_name)}" for id_name in ids)
    measured = [
        column(header_name) for header_name in dict.fromkeys(header) if header_name not in ids
    ]
    reads = [measured[i : i + COLUMNS_PER_READ] for i in range(0, len(measured), COLUMNS_PER_READ)]
    select = " UNION ALL ".join(
        f"SELECT * FROM (UNPIVOT (SELECT row_number() OVER () - 1 AS {ROW}{kept}, "
        f"{', '.join(read)} FROM {scan}) ON {', '.join(read)} INTO NAME {into} VALUE {value}) "
        f"WHERE {where}"
        for read in reads
    )
    with in_file_order(con):
        return Table(con, name).save(name, select)


def count_rows(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    delimiter = detect_file_delimiter(path)
    scan = _scan(path, read_header(path, delimiter), delimiter)
    [(rows,)] = con.execute(f"SELECT count(*) FROM {scan}").fetchall()
    return rows


def _read_delimited(
    con: duckdb.DuckDBPyConnection,
    path: Path,
    name: str,
    header: Sequence[str],
    delimiter: str,
) -> Table:
    if not header:
        return Table(con, name).view(name, f"SELECT 0 AS {ROW} WHERE FALSE")
    kept = ", ".join(column(header_name) for header_name in dict.fromkeys(header))
    with in_file_order(con):
        con.execute(
            f"CREATE OR REPLACE TABLE {name}_file AS SELECT * FROM {_scan(path, header, delimiter)}"
        )
    return Table(con, f"{name}_file").view(name, f"SELECT rowid AS {ROW}, {kept} FROM {name}_file")


def _scan(path: Path, header: Sequence[str], delimiter: str) -> str:
    last_of_each = {header_name: i for i, header_name in enumerate(header)}
    physical = [
        _encoded(header_name) if last_of_each[header_name] == i else f"^_shadowed{i}"
        for i, header_name in enumerate(header)
    ]
    columns = "{" + ", ".join(f"{literal(p)}: 'VARCHAR'" for p in physical) + "}"
    return (
        f"read_csv({literal(str(path))}, delim={literal(delimiter)}, header=false, skip=1, "
        f"quote='\"', escape='\"', columns={columns}, "
        f"force_not_null=[{', '.join(map(literal, physical))}], null_padding=true, "
        "strict_mode=false, auto_detect=false, parallel=false)"
    )


@contextmanager
def in_file_order(con: duckdb.DuckDBPyConnection) -> Generator[None]:
    [(threads,)] = con.execute("SELECT current_setting('threads')").fetchall()
    con.execute("SET preserve_insertion_order = true")
    con.execute("SET threads = 1")
    try:
        yield
    finally:
        con.execute(f"SET threads = {threads}")
        con.execute("SET preserve_insertion_order = false")


def number_lines(
    table: Table,
    name: str,
    columns: Sequence[str],
    *,
    order: Sequence[str] = (ROW,),
    collapse_breaks: bool = False,
) -> Table:
    keys = ", ".join(order)
    rows, distinct = table.one(f"SELECT count(*), count(DISTINCT row({keys})) FROM {table.name}")
    if rows != distinct:
        raise ValueError(
            f"{rows - distinct} row(s) of {table.name} share their place in the file with "
            "another row, so it can't be written in one order. This is a bug in edna2dwc"
        )
    lines = table.save(
        f"{name}_lines",
        f"SELECT {keys}, row_number() OVER (ORDER BY {keys}) - 1 AS {LINE} FROM {table.name}",
    )
    pattern = "[\t\r\n]+" if collapse_breaks else "[\t\r\n]"
    cells = "".join(
        f", regexp_replace(coalesce({table.name}.{column(c)}, ''), '{pattern}', ' ', 'g') "
        f"AS {column(c)}"
        for c in columns
    )
    same_key = " AND ".join(
        f"{table.name}.{key} IS NOT DISTINCT FROM {lines.name}.{key}" for key in order
    )
    return table.save(
        name,
        f"SELECT {lines.name}.{LINE} AS {ROW}{cells} "
        f"FROM {table.name} JOIN {lines.name} ON {same_key}",
    )


def write_lines(numbered: Table, path: Path, columns: Sequence[str]) -> None:
    ensure_parent_dir(path)
    if not columns:
        path.write_text("", encoding="utf-8")
        return
    selected = ", ".join(column(c) for c in columns)
    rows, size = numbered.one(
        f"SELECT count(*), sum({' + '.join(f'strlen({column(c)}) + 1' for c in columns)}) "
        f"FROM {numbered.name}"
    )
    per_batch = max(1, WRITE_BATCH_BYTES * rows // max(size or 0, 1))
    body = path.with_name(path.name + ".body")
    with path.open("w", encoding="utf-8", newline="") as out:
        out.write("\t".join(re.sub("[\t\r\n]+", " ", c) for c in columns) + "\n")
        for start in range(0, rows, per_batch):
            numbered.con.execute(
                f"COPY (SELECT {selected} FROM {numbered.name} "
                f"WHERE {ROW} >= {start} AND {ROW} < {start + per_batch} ORDER BY {ROW}) TO ? "
                "(FORMAT csv, HEADER false, DELIMITER '\t', QUOTE '', ESCAPE '', NULLSTR '')",
                [str(body)],
            )
            with body.open(encoding="utf-8", newline="") as batch:
                shutil.copyfileobj(batch, out)
    body.unlink(missing_ok=True)


def write_tsv(
    table: Table,
    path: Path,
    columns: Sequence[str],
    *,
    order: Sequence[str] = (ROW,),
    collapse_breaks: bool = False,
) -> None:
    if not columns:
        write_lines(table, path, columns)
        return
    numbered = number_lines(
        table, f"{table.name}_numbered", columns, order=order, collapse_breaks=collapse_breaks
    )
    write_lines(numbered, path, columns)
