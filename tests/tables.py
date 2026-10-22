from __future__ import annotations

from collections.abc import Mapping, Sequence

import duckdb

from edna2dwc.common.table import Table, from_dicts


def table_of(
    rows: Sequence[Mapping[str, str]],
    name: str = "source",
    con: duckdb.DuckDBPyConnection | None = None,
) -> Table:
    return from_dicts(con or duckdb.connect(), name, rows)


def dicts(table: Table) -> list[dict[str, str]]:
    return table.dicts()
