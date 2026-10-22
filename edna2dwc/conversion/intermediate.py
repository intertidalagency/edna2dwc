from __future__ import annotations

from pathlib import Path

import duckdb

from edna2dwc.common.findings import ERROR, FindingsLog
from edna2dwc.common.table import ROW, Table, column, connect, read_tsv
from edna2dwc.common.tsv import NotTabSeparatedError, read_tab_separated_header
from edna2dwc.taxonomy.unassigned import is_no_assignment

REQUIRED_COLUMNS = ("sampleID", "featureID", "count")
TAXONOMY_COLUMN = "taxonomy"
RANK_COLUMNS = ("kingdom", "phylum", "class", "order", "family", "genus")
NAME_COLUMNS = (*RANK_COLUMNS, "species", "scientificname")
WRITTEN_BY_TAXONOMY = frozenset(
    {
        "scientificnameid",
        "taxonrank",
        "scientificnameauthorship",
        "taxonomicstatus",
        "taxonconceptid",
    }
)
MARKER_COLUMN = "marker"
SEQUENCE_COLUMN = "sequence"
RESERVED_COLUMNS = frozenset(
    {*REQUIRED_COLUMNS, TAXONOMY_COLUMN, *RANK_COLUMNS, MARKER_COLUMN, SEQUENCE_COLUMN}
)


class IntermediateMissing(FileNotFoundError):
    pass


def require_intermediate(path: Path) -> None:
    if not path.exists():
        raise IntermediateMissing(f"{path} does not exist. Read the inputs into it first")


class IntermediateInvalid(ValueError):
    pass


def require_valid(path: Path, con: duckdb.DuckDBPyConnection) -> Table:
    log, table = _validate(path, con)
    errors = [f.message for f in log.findings if f.severity == ERROR]
    if errors or table is None:
        raise IntermediateInvalid(
            f"{path} breaks the intermediate table's schema: {'; '.join(errors)}. Fix the reader "
            "script, record it again and run assemble"
        )
    return table


def validate_intermediate(path: Path) -> FindingsLog:
    with connect() as con:
        return _validate(path, con)[0]


def _validate(path: Path, con: duckdb.DuckDBPyConnection) -> tuple[FindingsLog, Table | None]:
    log = FindingsLog()
    try:
        header = read_tab_separated_header(path)
    except NotTabSeparatedError as error:
        log.add("CONTRACT_INVALID", str(error))
        return log, None

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

    if not _lineage_columns(header):
        log.add(
            "CONTRACT_COLUMN_MISSING",
            "No column names a taxon: give a `taxonomy` lineage, rank columns from kingdom to "
            "genus, `species` or `scientificName`",
        )
    for name in header:
        if name.lower() in WRITTEN_BY_TAXONOMY:
            log.add(
                "CONTRACT_COLUMN_RESERVED",
                f"{name!r} is written by resolve-taxonomy, so the table can't carry it: put an "
                "NCBI taxid in `ncbi_taxid`, a WoRMS AphiaID or LSID in `source_taxon_id`, and "
                "keep anything else under another name, which build publishes in dynamicProperties",
            )

    can_check_rows = not duplicate_names and all(name in header for name in REQUIRED_COLUMNS)
    if not can_check_rows:
        return log, None
    table = read_tsv(con, path, "source", header)
    _check_rows(table, header, log)
    return log, table


_SHOWN_ROWS = 5
_READER_HINT = ". The reader script wrote none for them: check which sheet and column it reads"


def _rows_named(rows: list[int], count: int) -> str:
    shown = ", ".join(str(i) for i in rows)
    hidden = count - _SHOWN_ROWS
    if count == 1:
        return f"row {shown}"
    return f"rows {shown} and {hidden} more" if hidden > 0 else f"rows {shown}"


def _lineage_columns(header: list[str]) -> list[str]:
    return [h for h in header if h == TAXONOMY_COLUMN or h.lower() in NAME_COLUMNS]


def _check_rows(table: Table, header: list[str], log: FindingsLog) -> None:
    sample, feature, count = (column(name) for name in REQUIRED_COLUMNS)
    number = f"try_cast({count} AS DOUBLE)"
    checks = [
        *(
            (
                "CONTRACT_INVALID",
                f"have a tab, CR or LF in column {name!r}",
                "",
                f"regexp_matches({column(name)}, '[\\t\\r\\n]')",
            )
            for name in dict.fromkeys(header)
        ),
        ("CONTRACT_INVALID", "have no sampleID", _READER_HINT, f"{sample} = ''"),
        ("CONTRACT_INVALID", "have no featureID", _READER_HINT, f"{feature} = ''"),
        (
            "CONTRACT_TYPE_INVALID",
            "have a count that is not a finite number",
            "",
            f"{number} IS NULL OR NOT isfinite({number})",
        ),
        ("CONTRACT_TYPE_INVALID", "have a negative count", "", f"{number} < 0"),
    ]
    failing = table.one(
        "SELECT " + ", ".join(f"count_if({where})" for *_, where in checks) + f" FROM {table.name}"
    )
    for (code, what, hint, where), failed in zip(checks, failing):
        if failed:
            _add_rows(log, code, what, hint, *table.first(f"{ROW} + 2", where))
    repeated = table.view(
        "repeated",
        f"SELECT {ROW} FROM {table.name} JOIN (SELECT {sample}, {feature}, min({ROW}) AS first "
        f"FROM {table.name} GROUP BY ALL HAVING count(*) > 1) USING ({sample}, {feature}) "
        f"WHERE {ROW} > first",
    )
    what = "repeat an earlier row's (sampleID, featureID)"
    _add_rows(log, "CONTRACT_INVALID", what, "", *repeated.first(f"{ROW} + 2", "TRUE"))
    lineages = _lineage_columns(header)
    if lineages and not _has_lineage(table, lineages):
        log.add(
            "TAXONOMY_BLANK",
            f"No row has a lineage in {', '.join(lineages)}, so every occurrence would be "
            "published as the placeholder taxon Biota incertae sedis. Check which column the reader script reads "
            "the taxonomy from",
        )


def _add_rows(log: FindingsLog, code: str, what: str, hint: str, count: int, rows: list) -> None:
    if count:
        log.add(code, f"{count} row(s) {what} ({_rows_named(rows, count)}){hint}", count=count)


def _has_lineage(table: Table, lineages: list[str]) -> bool:
    values = " UNION ".join(
        f"SELECT trim({column(name)}) AS value FROM {table.name}" for name in lineages
    )
    found = table.con.execute(f"SELECT DISTINCT value FROM ({values}) WHERE value <> ''")
    while batch := found.fetchmany(1000):
        if any(not is_no_assignment(value) for (value,) in batch):
            return True
    return False


def markers(table: Table) -> set[str]:
    return {
        marker
        for (marker,) in table.rows(f"SELECT DISTINCT {table.text('marker')} FROM {table.name}")
    }
