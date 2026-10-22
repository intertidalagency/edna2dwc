from __future__ import annotations

from dataclasses import dataclass

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import ROW, Table, column

TERM_CLASS = "DNADerivedData"
ID_COLUMN = "occurrenceID"


@dataclass(frozen=True)
class DnaResult:
    core_header: list[str]
    dna: Table | None
    dna_header: list[str]
    findings: FindingsLog


def select_dna_columns(
    header: list[str], term_table: dict, *, id_column: str = ID_COLUMN
) -> list[str]:
    return [
        column
        for column in header
        if column != id_column and term_table.get(column, {}).get("class") == TERM_CLASS
    ]


def select_and_build_dna(
    core: Table, header: list[str], term_table: dict, *, id_column: str = ID_COLUMN
) -> DnaResult:
    findings = FindingsLog()
    selected = select_dna_columns(header, term_table, id_column=id_column)
    if not selected:
        return DnaResult(list(header), None, [], findings)

    values = ", ".join(f"{core.text(c)} AS {column(c)}" for c in selected)
    dna = core.view(
        "dna_rows",
        f"SELECT {ROW}, {core.text(id_column)} AS {column(id_column)}, {values} "
        f"FROM {core.name} WHERE {' OR '.join(f'{core.text(c)} <> {chr(39) * 2}' for c in selected)}",
    )
    moved = set(selected)
    findings.add(
        "DNA_TERMS_ROUTED",
        f"moved into the {TERM_CLASS} extension, keyed by {id_column}: {', '.join(selected)}",
        count=len(selected),
    )
    if without := core.count() - dna.count():
        findings.add(
            "DNA_TERMS_ROUTED",
            f"core rows with no {TERM_CLASS} value, so no extension row was written",
            count=without,
        )
    return DnaResult([c for c in header if c not in moved], dna, [id_column, *selected], findings)
