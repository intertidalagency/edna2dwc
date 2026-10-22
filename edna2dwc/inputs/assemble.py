from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path

import duckdb

from edna2dwc.common.findings import Finding, FindingsLog
from edna2dwc.common.table import (
    ROW,
    Table,
    column,
    connect,
    count_rows,
    from_rows,
    internal,
    read_delimited,
    read_unpivoted,
    write_tsv,
)
from edna2dwc.common.text import first_few
from edna2dwc.common.tsv import open_text, read_header
from edna2dwc.conversion.intermediate import REQUIRED_COLUMNS

SAMPLE, FEATURE, COUNT = REQUIRED_COLUMNS
MARKER = "marker"
SEQUENCE = "sequence"
SEQUENCE_COLUMNS = (SEQUENCE, "DNA_sequence")
FILE = internal("file")
POSITION = internal("position")
SOURCE_NAME = internal("source_name")
ORDER = (FILE, ROW, POSITION)
LISTED = 5


class AssembleError(ValueError):
    pass


@dataclass(frozen=True)
class Sources:
    counts: tuple[Path, ...]
    features: tuple[Path, ...] = ()
    samples: tuple[Path, ...] = ()
    sequences: tuple[Path, ...] = ()
    keep_zeros: bool = False


@dataclass(frozen=True)
class Assembly:
    rows: int
    findings: FindingsLog


def assemble(sources: Sources, out_path: Path) -> Assembly:
    findings = FindingsLog()
    with connect() as con:
        table = _counts(con, sources, findings)
        origins = dict.fromkeys(table.columns, _named(sources.counts))
        if sources.features:
            features = _lookup(con, "features", sources.features, FEATURE, findings)
            table = _join(table, features, FEATURE, _named(sources.features), origins, findings)
        if sources.sequences:
            sequences = _sequences(con, sources.sequences, table, findings)
            table = _join(table, sequences, FEATURE, _named(sources.sequences), origins, findings)
        if sources.samples:
            samples = _lookup(con, "samples", sources.samples, SAMPLE, findings)
            table = _join(table, samples, SAMPLE, _named(sources.samples), origins, findings)
        rows = table.count()
        if not rows:
            raise AssembleError(
                "the count tables give no row with a nonzero count, so there is nothing to "
                "publish. Check that the reader script wrote the counts, and that the count "
                "columns hold numbers"
            )
        extra = sorted(name for name in table.columns if name not in REQUIRED_COLUMNS)
        write_tsv(table, out_path, [*REQUIRED_COLUMNS, *extra], order=ORDER)
        return Assembly(rows, findings)


def _counts(con: duckdb.DuckDBPyConnection, sources: Sources, findings: FindingsLog) -> Table:
    parts = []
    for index, path in enumerate(sources.counts):
        header = read_header(path)
        if FEATURE not in header:
            raise AssembleError(
                f"{path} has no featureID column. Name the feature column featureID in the "
                "reader script"
            )
        if all(name in header for name in REQUIRED_COLUMNS):
            source = read_delimited(con, path, f"counts_{index}")
            part = source.view(
                f"long_{index}",
                f"SELECT {index} AS {FILE}, {ROW}, 0 AS {POSITION}, "
                f"{_visible(source)} FROM {source.name} "
                f"WHERE {_nonzero(column(COUNT), sources.keep_zeros)}",
            )
            _report_dropped(findings, path, source.count() - part.count(), "zero-count row(s)")
        else:
            part = _melted(con, path, header, index, sources.keep_zeros, findings)
        rows, total = part.one(
            f"SELECT count(*), sum(try_cast({column(COUNT)} AS DOUBLE)) FROM {part.name}"
        )
        findings.add(
            "INPUT_TOTALS",
            f"{path.name}: {rows} count row(s), with a count total of {_number(total)}",
            count=rows,
        )
        parts.append(part)
    union = " UNION ALL BY NAME ".join(f"SELECT * FROM {part.name}" for part in parts)
    return Table(con, "counts").save("counts", union)


def _melted(
    con: duckdb.DuckDBPyConnection,
    path: Path,
    header: Sequence[str],
    index: int,
    keep_zeros: bool,
    findings: FindingsLog,
) -> Table:
    kept = [name for name in (FEATURE, MARKER) if name in header]
    samples = [name for name in dict.fromkeys(header) if name not in kept]
    if not samples:
        raise AssembleError(f"{path} has a featureID column and no sample columns")
    names = from_rows(
        con,
        f"sample_names_{index}",
        {SOURCE_NAME: "VARCHAR", SAMPLE: "VARCHAR", POSITION: "INTEGER"},
        [(column(name)[1:-1], name, i) for i, name in enumerate(samples)],
    )
    unpivoted = read_unpivoted(
        con,
        path,
        f"unpivoted_{index}",
        kept,
        SOURCE_NAME,
        "value",
        f"value <> '' AND {_nonzero('value', keep_zeros)}",
    )
    holding_text = [
        name
        for (name,) in unpivoted.rows(
            f"SELECT {names.name}.{column(SAMPLE)} FROM (SELECT DISTINCT {SOURCE_NAME} "
            f"FROM {unpivoted.name} WHERE value <> '' AND try_cast(value AS DOUBLE) IS NULL) "
            f"JOIN {names.name} USING ({SOURCE_NAME}) ORDER BY {names.name}.{POSITION}"
        )
    ]
    if holding_text:
        raise AssembleError(
            f"{path}: {_listed(holding_text)} hold text, so they aren't sample counts. A wide "
            "count table holds featureID, an optional marker and one column per sample; give "
            "feature columns with --features"
        )
    dropped = count_rows(con, path) * len(samples) - unpivoted.count()
    _report_dropped(findings, path, dropped, "empty or zero cell(s) of the wide count table")
    return unpivoted.save(
        f"melted_{index}",
        f"SELECT {index} AS {FILE}, {unpivoted.name}.{ROW}, {names.name}.{POSITION}, "
        f"{', '.join(f'{unpivoted.name}.{column(n)}' for n in kept)}, "
        f"{names.name}.{column(SAMPLE)}, value AS {column(COUNT)} FROM {unpivoted.name} "
        f"JOIN {names.name} USING ({SOURCE_NAME})",
    )


def _nonzero(value: str, keep_zeros: bool) -> str:
    return "TRUE" if keep_zeros else f"coalesce(try_cast(trim({value}) AS DOUBLE) <> 0, TRUE)"


def _report_dropped(findings: FindingsLog, path: Path, dropped: int, what: str) -> None:
    if dropped:
        findings.add(
            "PRESENCE_ONLY_FILTERED",
            f"{path.name}: {dropped} {what} were not written as rows, because a zero read "
            "count is not evidence of absence",
            count=dropped,
        )


def _lookup(
    con: duckdb.DuckDBPyConnection,
    role: str,
    paths: Sequence[Path],
    key: str,
    findings: FindingsLog,
) -> Table:
    parts = []
    for index, path in enumerate(paths):
        part = read_delimited(con, path, f"{role}_{index}")
        if key not in part.columns:
            raise AssembleError(f"{path} has no {key} column, which it joins on")
        findings.add("INPUT_TOTALS", f"{path.name}: {part.count()} row(s)", count=part.count())
        parts.append(part)
    union = " UNION ALL BY NAME ".join(f"SELECT {_visible(p)} FROM {p.name}" for p in parts)
    table = Table(con, role).save(role, union)
    repeated = [
        found
        for (found,) in table.rows(
            f"SELECT {column(key)} FROM {role} GROUP BY 1 HAVING count(*) > 1 "
            f"ORDER BY 1 LIMIT {LISTED + 1}"
        )
    ]
    if repeated:
        stacked = (
            f". Each --{role} table is stacked under the others, not joined to them: "
            f"join them into one --{role} table in the reader script"
            if len(paths) > 1
            else ""
        )
        raise AssembleError(
            f"{_named(paths)} give more than one row for {key} {_listed(repeated)}, so a "
            f"count row would join to each of them{stacked}"
        )
    return table


def _sequences(
    con: duckdb.DuckDBPyConnection, paths: Sequence[Path], table: Table, findings: FindingsLog
) -> Table:
    if given := [name for name in SEQUENCE_COLUMNS if table.has(name)]:
        raise AssembleError(
            f"the tables already have a {given[0]} column, which --sequences would overwrite"
        )
    sequences: dict[str, str] = {}
    for path in paths:
        records = _fasta(path)
        findings.add("INPUT_TOTALS", f"{path.name}: {len(records)} record(s)", count=len(records))
        for record_id, sequence in records:
            if sequences.get(record_id, sequence) != sequence:
                raise AssembleError(f"FASTA ID {record_id!r} has two different sequences")
            sequences[record_id] = sequence
    return from_rows(
        con, "sequences", {FEATURE: "VARCHAR", SEQUENCE: "VARCHAR"}, list(sequences.items())
    )


def _fasta(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    with open_text(path) as f:
        for line in f:
            if line.startswith(">"):
                words = line[1:].split()
                if not words:
                    raise AssembleError(f"{path} has a record with no ID after its '>'")
                records.append((words[0], ""))
            elif records and line.strip():
                record_id, sequence = records[-1]
                records[-1] = (record_id, sequence + line.strip())
    if not records:
        raise AssembleError(f"{path} has no FASTA record, a line starting with '>'")
    return records


def _join(
    left: Table,
    right: Table,
    key: str,
    named: str,
    origins: dict[str, str],
    findings: FindingsLog,
) -> Table:
    added = [name for name in right.columns if name != key]
    if MARKER in added and left.has(MARKER):
        raise AssembleError(
            f"{named} has a {MARKER!r} column, which belongs on the --counts tables only: "
            f"each feature's marker comes from its count table, so drop it from {named}"
        )
    if shared := [name for name in added if left.has(name)]:
        earlier = " and ".join(sorted({origins[name] for name in shared}))
        raise AssembleError(
            f"{_listed(shared)} come from both {named} and {earlier}. Give each column in one "
            "table only"
        )
    origins.update(dict.fromkeys(added, named))
    keyed = column(key)
    for found, missing, code, where in (
        (
            left,
            right,
            "JOIN_METADATA_MISSING",
            f"have no row in {named}, so those rows keep blank columns from it",
        ),
        (right, left, "JOIN_UNMATCHED", f"in {named} match no count row"),
    ):
        unmatched = [
            value
            for (value,) in found.rows(
                f"SELECT DISTINCT {keyed} FROM {found.name} WHERE {keyed} NOT IN "
                f"(SELECT {keyed} FROM {missing.name}) ORDER BY 1"
            )
        ]
        if unmatched:
            findings.add(
                code,
                f"{len(unmatched)} {key}(s) {_listed(unmatched)} {where}",
                count=len(unmatched),
            )
    selected = ", ".join(f"{right.name}.{column(name)}" for name in added)
    return left.save(
        f"joined_{right.name}",
        f"SELECT {left.name}.*{', ' + selected if selected else ''} FROM {left.name} "
        f"LEFT JOIN {right.name} ON {left.name}.{keyed} = {right.name}.{keyed}",
    )


def _visible(table: Table) -> str:
    return ", ".join(column(name) for name in table.columns)


def _named(paths: Sequence[Path]) -> str:
    return ", ".join(path.name for path in paths)


def _number(value: float | None) -> str:
    if value is None:
        return "0"
    return str(int(value)) if float(value).is_integer() else str(value)


def _listed(values: Sequence[str]) -> str:
    return first_few([repr(v) for v in values], LISTED)


def write_record(assembly: Assembly, record_path: Path, out_path: Path) -> None:
    written = out_path.stat()
    record = {
        "intermediate": {"size": written.st_size, "mtime_ns": written.st_mtime_ns},
        "findings": assembly.findings.to_list(),
    }
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def recorded_findings(record_path: Path, intermediate: Path) -> FindingsLog:
    if not record_path.exists() or not intermediate.exists():
        return FindingsLog()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    current = intermediate.stat()
    if record["intermediate"] != {"size": current.st_size, "mtime_ns": current.st_mtime_ns}:
        return FindingsLog()
    return FindingsLog([Finding(**entry) for entry in record["findings"]])
