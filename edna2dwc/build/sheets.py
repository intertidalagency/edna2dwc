from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from edna2dwc.build import filter_controls
from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import ROW, Table, lookup, matching, read_tsv
from edna2dwc.common.text import first_few
from edna2dwc.common.tsv import read_header, read_rows
from edna2dwc.conversion import artifacts
from edna2dwc.conversion.provenance import (
    CONFIRMED,
    Answer,
    SheetRefused,
    not_a_persons_reply,
    refuse_machine_confirmed,
    refuse_unprovenanced,
)
from edna2dwc.terms import map_terms
from edna2dwc.terms.map_terms import JOINED_FIELDS

DERIVED_FIELDS_TRIGGER_CODES = frozenset({"COORDINATE_SIGN_SUSPECT"})


@dataclass(frozen=True)
class Sheet:
    name: str
    title: str

    @property
    def proposal(self) -> Path:
        return artifacts.PROPOSED_DIR / f"{self.name}.tsv"

    @property
    def confirmed(self) -> Path:
        return artifacts.CONFIRMED_DIR / f"{self.name}.tsv"


CONTROL_ROSTER = Sheet("control_roster", "Sample roster: which samples are controls")
TERM_MAPPING = Sheet("term_mapping", "Source column to term mapping")
TAXA = Sheet("taxa", "Resolved taxonomy")
DERIVED_VALUES = Sheet("derived_values", "Derived fields for the first 20 samples")
SHEETS = (CONTROL_ROSTER, TERM_MAPPING, TAXA, DERIVED_VALUES)


LISTED_ROWS = 10


@dataclass(frozen=True)
class RowsChanged:
    changed: int = 0
    unconfirmed: int = 0
    first_unconfirmed: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, answers: dict[str, Answer]) -> RowsChanged:
        unconfirmed = [row for row, answer in answers.items() if answer.unconfirmed]
        return cls(len(answers), len(unconfirmed), unconfirmed[:LISTED_ROWS])


@dataclass(frozen=True)
class SheetReview:
    sheet: Sheet
    reason: str
    confirmed: bool
    rows: RowsChanged = field(default_factory=RowsChanged)

    @property
    def open(self) -> bool:
        return bool(self.reason) and not self.confirmed

    @property
    def unconfirmed_summary(self) -> str:
        return (
            f"{self.sheet.confirmed.as_posix()} row(s) "
            f"{first_few(self.rows.first_unconfirmed, LISTED_ROWS, self.rows.unconfirmed)}"
        )


SHEET_KEYS = {TAXA: "lineage_key", DERIVED_VALUES: "sampleID"}


def confirmed_rows(root: Path, sheet: Sheet) -> list[dict[str, str]] | None:
    if not (root / sheet.confirmed).exists():
        return None
    rows = list(read_rows(root / sheet.confirmed, delimiter="\t"))
    refuse_machine_confirmed(
        sheet.confirmed, [(row.get(SHEET_KEYS[sheet], ""), row) for row in rows]
    )
    return rows


def confirmed_table(root: Path, sheet: Sheet, con: duckdb.DuckDBPyConnection) -> Table | None:
    if not (root / sheet.confirmed).exists():
        return None
    path = root / sheet.confirmed
    table = read_tsv(con, path, f"confirmed_{sheet.name}", read_header(path, "\t"))
    reply = table.text(CONFIRMED)
    machine = lookup(
        table,
        "machine_replies",
        [reply],
        {"problem": "VARCHAR"},
        lambda found: (not_a_persons_reply(found),),
        keep=lambda _, problem: bool(problem[0]),
    )
    machine_written = table.rows(
        f"SELECT {table.text(SHEET_KEYS[sheet])}, {reply} FROM {table.name} "
        f"JOIN {machine.name} ON {matching(machine, [reply])} ORDER BY {ROW} LIMIT 3"
    )
    refuse_machine_confirmed(
        sheet.confirmed, [(key, {CONFIRMED: found}) for key, found in machine_written]
    )
    return table


def confirmed_mapping(root: Path) -> list[map_terms.MappingProposal]:
    if not (root / TERM_MAPPING.confirmed).exists():
        return []
    try:
        rows = map_terms.read_mapping_tsv(
            (root / TERM_MAPPING.confirmed).read_text(encoding="utf-8")
        )
    except ValueError as error:
        raise SheetRefused(f"{TERM_MAPPING.confirmed.as_posix()}: {error}") from error
    refuse_machine_confirmed(
        TERM_MAPPING.confirmed,
        [(row.source_column, {"confirmed": row.confirmed}) for row in rows],
    )
    return rows


def apply_confirmed_mapping(
    proposed: list[map_terms.MappingProposal],
    confirmed: list[map_terms.MappingProposal],
    header: list[str],
) -> tuple[list[map_terms.MappingProposal], FindingsLog]:
    _check_every_changed_row_has_provenance(confirmed, proposed)
    _check_no_row_overwrites_the_taxonomy(confirmed)
    confirmed_by_column = {row.source_column: row for row in confirmed}
    proposed_columns = {row.source_column for row in proposed}
    applied = [confirmed_by_column.get(row.source_column, row) for row in proposed]
    applied += [row for row in confirmed if row.source_column not in proposed_columns]
    log = FindingsLog()
    unmatched = _unmatched_mapping_rows(confirmed, header)
    if unmatched:
        log.add(
            "CONFIRMED_ROW_UNMATCHED",
            f"{len(unmatched)} row(s) of {TERM_MAPPING.confirmed.as_posix()} name a column the "
            f"table does not have: {', '.join(unmatched)}. Remove each row, or correct its "
            "source_column, then build again",
            count=len(unmatched),
        )
    return map_terms.review_order(applied), log


def _unmatched_mapping_rows(rows: list[map_terms.MappingProposal], header: list[str]) -> list[str]:
    return [
        row.source_column
        for row in rows
        if not map_terms.is_constant_row(row.source_column) and row.source_column not in header
    ]


def _check_every_changed_row_has_provenance(
    confirmed: list[map_terms.MappingProposal], proposed: list[map_terms.MappingProposal]
) -> None:
    as_proposed = {(row.source_column, row.target) for row in proposed}
    unprovenanced = [
        row.source_column
        for row in confirmed
        if (row.source_column, row.target) not in as_proposed and not row.provenance.strip()
    ]
    refuse_unprovenanced(TERM_MAPPING.confirmed, unprovenanced)


def _check_no_row_overwrites_the_taxonomy(rows: list[map_terms.MappingProposal]) -> None:
    overwriting = [
        f"{row.source_column} -> {row.target}" for row in rows if row.target in JOINED_FIELDS
    ]
    if overwriting:
        raise SheetRefused(
            f"{TERM_MAPPING.confirmed.as_posix()} maps a column onto a term the taxonomy join "
            f"writes from {artifacts.RESOLVED_TAXONOMY}: {', '.join(overwriting)}. Delete those "
            f"rows. To change a taxon, put its row in {TAXA.confirmed.as_posix()} with its "
            "provenance and confirmed columns filled. To publish the source's own taxon IDs, "
            "name the column ncbi_taxid for NCBI taxonomy IDs, which become taxonConceptID, or "
            "source_taxon_id for WoRMS AphiaIDs, in the intermediate table, then rerun "
            "resolve-taxonomy.",
        )


def controls_reason(roster: list[dict[str, str]]) -> str:
    guessed = [
        row["sampleID"]
        for row in roster
        if row["action"] == "excluded" and row["basis"] == filter_controls.SAMPLE_ID_BASIS
    ]
    if not guessed:
        return ""
    return (
        f"{len(guessed)} sample(s) excluded as controls on a keyword in the sampleID alone: "
        f"{', '.join(guessed)}"
    )


def mapping_reason(findings: FindingsLog, unmapped: int, moving: list[str]) -> str:
    ambiguous = [f for f in findings.findings if f.code == "TERM_AMBIGUOUS"]
    parts = []
    if ambiguous:
        parts.append(f"{len(ambiguous)} ambiguous mapping(s)")
    if unmapped - len(moving) > 0:
        parts.append(f"{unmapped - len(moving)} column(s) staying in dynamicProperties")
    if moving:
        parts.append(
            f"{', '.join(moving)} will move to extendedmeasurementorfact; a row with target "
            "dynamicProperties keeps a column out of it"
        )
    return "; ".join(parts)


def taxa_reason(lock: list[dict[str, str]], resolution: FindingsLog) -> str:
    reason = f"{len(lock)} distinct lineage(s) resolved"
    if codes := [finding.code for finding in resolution.findings]:
        reason += f", with resolution findings: {', '.join(codes)}"
    return reason


def derived_reason(findings: FindingsLog) -> str:
    return "; ".join(
        f"{f.code}: {f.message}"
        for f in findings.findings
        if f.code in DERIVED_FIELDS_TRIGGER_CODES
    )


LISTED_UNCONFIRMED = 5


def describe_unconfirmed(keys: list[str], sheet_rows: list[str], total: int) -> str:
    named = [first_few(keys, LISTED_UNCONFIRMED)] if keys else []
    return f"{total} answer(s) no person has confirmed: {', '.join([*named, *sheet_rows])}"


def record_reviews(reviews: list[SheetReview], *, automatic: bool) -> FindingsLog:
    log = FindingsLog()
    for review in reviews:
        if review.confirmed:
            log.add(
                "CONFIRMED_SHEET_APPLIED",
                f"{review.sheet.confirmed.as_posix()} was applied over "
                f"{review.sheet.proposal.as_posix()}",
            )
        elif review.open and automatic:
            log.add(
                "PROPOSAL_ACCEPTED",
                f"{review.sheet.proposal.as_posix()} was used as written: {review.reason}",
            )
    return log
