from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re


_PREFIX_TO_RANK = {
    "d": "kingdom",
    "k": "kingdom",
    "p": "phylum",
    "c": "class",
    "o": "order",
    "f": "family",
    "g": "genus",
}
_RANK_PREFIX_RE = re.compile(r"^([dkpcofgs])__(.*)$")

TAXONOMY_COLUMN = "taxonomy"


@dataclass
class LineageEntry:
    lineage_key: str
    terminal_name: str
    source_ranks: dict[str, str]
    row_count: int = 0
    ncbi_taxid: str = ""
    source_taxon_id: str = ""

    def to_row(self) -> dict[str, str]:
        row = {"lineage_key": self.lineage_key, "terminal_name": self.terminal_name}
        for rank in RANK_COLUMNS:
            row[f"source_{rank}"] = self.source_ranks.get(rank, "")
        row["row_count"] = str(self.row_count)
        row["ncbi_taxid"] = self.ncbi_taxid
        row["source_taxon_id"] = self.source_taxon_id
        return row


@dataclass
class DeriveLineageResult:
    lineage_rows: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedTaxonomy:
    ranks: dict[str, str]
    terminal: str


def parse_taxonomy_string(taxonomy: str) -> ParsedTaxonomy:
    ranks: dict[str, str] = {}



    ordered_ranks = "|".join(source_ranks.get(rank, "") for rank in RANK_COLUMNS)


    entries: dict[str, LineageEntry] = {}
    lineage_rows = [e.to_row() for e in sorted(entries.values(), key=lambda e: e.lineage_key)]
