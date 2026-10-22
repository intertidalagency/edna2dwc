from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from edna2dwc.common.table import ROW, Table, column, connect, internal, read_tsv
from edna2dwc.common.tsv import read_header
from edna2dwc.conversion import artifacts
from edna2dwc.validation import validate


@dataclass
class TableDiff:
    table: str
    columns_added: list[str] = field(default_factory=list)
    columns_removed: list[str] = field(default_factory=list)
    value_diff_counts: dict[str, int] = field(default_factory=dict)
    value_examples: list[dict] = field(default_factory=list)
    only_in_old: list[str] = field(default_factory=list)
    only_in_new: list[str] = field(default_factory=list)
    rows_only_in_old: int = 0
    rows_only_in_new: int = 0
    row_order_matches: bool = True

    @property
    def diverged(self) -> bool:
        return bool(
            self.columns_added
            or self.columns_removed
            or self.value_diff_counts
            or self.rows_only_in_old
            or self.rows_only_in_new
            or not self.row_order_matches
        )


@dataclass
class ComparisonResult:
    tables: list[TableDiff] = field(default_factory=list)
    eml_differs: bool = False
    tables_added: list[str] = field(default_factory=list)
    tables_removed: list[str] = field(default_factory=list)
    undeclared_in_old: list[str] = field(default_factory=list)
    undeclared_in_new: list[str] = field(default_factory=list)
    archive_sha256: str = ""

    @property
    def diverged(self) -> bool:
        return (
            self.eml_differs
            or bool(self.tables_added)
            or bool(self.tables_removed)
            or bool(self.undeclared_in_old)
            or bool(self.undeclared_in_new)
            or any(t.diverged for t in self.tables)
        )

    def to_dict(self) -> dict:
        return {
            "diverged": self.diverged,
            "eml_differs": self.eml_differs,
            "tables_added": self.tables_added,
            "tables_removed": self.tables_removed,
            "undeclared_in_old": self.undeclared_in_old,
            "undeclared_in_new": self.undeclared_in_new,
            "archive_sha256": self.archive_sha256,
            "tables": [
                {
                    "table": t.table,
                    "columns_added": t.columns_added,
                    "columns_removed": t.columns_removed,
                    "value_diff_counts": t.value_diff_counts,
                    "value_examples": t.value_examples,
                    "only_in_old": t.only_in_old,
                    "only_in_new": t.only_in_new,
                    "rows_only_in_old": t.rows_only_in_old,
                    "rows_only_in_new": t.rows_only_in_new,
                    "row_order_matches": t.row_order_matches,
                }
                for t in self.tables
            ],
        }


def _extract(zip_path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    resolved_dest = dest_dir.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            target = (resolved_dest / member).resolve()
            if not target.is_relative_to(resolved_dest):
                raise ValueError(f"{zip_path}: member {member!r} would extract outside {dest_dir}")
        z.extractall(dest_dir)
    return dest_dir


def _undeclared_members(zip_path: Path, declared: set[str]) -> list[str]:
    with zipfile.ZipFile(zip_path) as z:
        top_level = {name for name in z.namelist() if "/" not in name}
    expected = {"meta.xml", "eml.xml", *declared, *artifacts.REPORT_PAGE_FILENAMES}
    return sorted(top_level - expected)


def _compare_eml(old_dir: Path, new_dir: Path) -> bool:
    return (old_dir / "eml.xml").read_text(encoding="utf-8") != (new_dir / "eml.xml").read_text(
        encoding="utf-8"
    )


LISTED = 10
ID = internal("id")
FINGERPRINT = internal("fingerprint")
NTH = internal("nth")
OLD_ROW = internal("old_row")
NEW_ROW = internal("new_row")


def _compare_table(
    table_name: str, old_dir: Path, new_dir: Path, file_location: str, id_column: str
) -> TableDiff:
    diff = TableDiff(table=table_name)
    old_header = read_header(old_dir / file_location, delimiter="\t")
    new_header = read_header(new_dir / file_location, delimiter="\t")
    diff.columns_added = [c for c in new_header if c not in old_header]
    diff.columns_removed = [c for c in old_header if c not in new_header]
    shared = [c for c in old_header if c in new_header]
    with connect() as con:
        old = read_tsv(con, old_dir / file_location, "old", old_header)
        new = read_tsv(con, new_dir / file_location, "new", new_header)
        old_keys, new_keys = _keys(old, id_column, shared), _keys(new, id_column, shared)
        identical = _identical_pairs(old_keys, new_keys)
        old_rest = _unpaired(old_keys, identical, OLD_ROW)
        new_rest = _unpaired(new_keys, identical, NEW_ROW)
        diff.rows_only_in_old, diff.only_in_old = _rows_missing_from(old_rest, new_rest)
        diff.rows_only_in_new, diff.only_in_new = _rows_missing_from(new_rest, old_rest)
        changed = _pairs(old_rest, new_rest)
        diff.row_order_matches = _in_the_same_order(identical, changed)
        _compare_values(diff, old, new, changed, shared)
    return diff


def _keys(table: Table, id_column: str, shared: list[str]) -> Table:
    fingerprint = f"hash({', '.join(table.get(name) for name in shared)})" if shared else "0"
    return table.save(
        f"{table.name}_keys",
        f"SELECT {table.text(id_column)} AS {ID}, {fingerprint} AS {FINGERPRINT}, {ROW} "
        f"FROM {table.name}",
    )


def _identical_pairs(old_keys: Table, new_keys: Table) -> Table:
    def numbered_copies(keys: Table) -> str:
        return (
            f"SELECT *, row_number() OVER (PARTITION BY {ID}, {FINGERPRINT} ORDER BY {ROW}) "
            f"AS {NTH} FROM {keys.name}"
        )

    return old_keys.save(
        "identical",
        f"SELECT o.{ROW} AS {OLD_ROW}, n.{ROW} AS {NEW_ROW} "
        f"FROM ({numbered_copies(old_keys)}) o JOIN ({numbered_copies(new_keys)}) n "
        f"USING ({ID}, {FINGERPRINT}, {NTH})",
    )


def _unpaired(keys: Table, identical: Table, paired_row: str) -> Table:
    return keys.save(
        f"{keys.name}_unpaired",
        f"SELECT {ID}, row_number() OVER (PARTITION BY {ID} ORDER BY {ROW}) AS {NTH}, {ROW} "
        f"FROM {keys.name} ANTI JOIN {identical.name} ON {ROW} = {paired_row}",
    )


def _rows_missing_from(rows: Table, other: Table) -> tuple[int, list[str]]:
    missing = f"SELECT {ID}, {NTH} FROM {rows.name} EXCEPT SELECT {ID}, {NTH} FROM {other.name}"
    count = rows.one(f"SELECT count(*) FROM ({missing})")[0]
    first = rows.rows(f"SELECT DISTINCT {ID} FROM ({missing}) ORDER BY {ID} LIMIT {LISTED}")
    return count, [found for (found,) in first]


def _pairs(old_rest: Table, new_rest: Table) -> Table:
    return old_rest.save(
        "pairs",
        f"SELECT {ID}, o.{ROW} AS {OLD_ROW}, n.{ROW} AS {NEW_ROW} "
        f"FROM {old_rest.name} o JOIN {new_rest.name} n USING ({ID}, {NTH})",
    )


def _in_the_same_order(identical: Table, changed: Table) -> bool:
    paired = f"SELECT {OLD_ROW}, {NEW_ROW} FROM {identical.name} UNION ALL SELECT {OLD_ROW}, {NEW_ROW} FROM {changed.name}"
    return not identical.one(
        f"SELECT count(*) FROM (SELECT row_number() OVER (ORDER BY {OLD_ROW}) AS old_place, "
        f"row_number() OVER (ORDER BY {NEW_ROW}) AS new_place FROM ({paired})) "
        f"WHERE old_place != new_place"
    )[0]


def _compare_values(
    diff: TableDiff, old: Table, new: Table, pairs: Table, shared: list[str]
) -> None:
    examples = []
    for position, name in enumerate(shared):
        differing = (
            f"FROM {pairs.name} p JOIN {old.name} o ON o.{ROW} = p.{OLD_ROW} "
            f"JOIN {new.name} n ON n.{ROW} = p.{NEW_ROW} "
            f"WHERE o.{column(name)} IS DISTINCT FROM n.{column(name)}"
        )
        if count := pairs.one(f"SELECT count(*) {differing}")[0]:
            diff.value_diff_counts[name] = count
            examples += [
                (row, position, found, name, before, after)
                for row, found, before, after in pairs.rows(
                    f"SELECT p.{OLD_ROW}, p.{ID}, o.{column(name)}, n.{column(name)} {differing} "
                    f"ORDER BY p.{OLD_ROW} LIMIT {LISTED}"
                )
            ]
    diff.value_examples = [
        {"table": diff.table, "id": found, "column": name, "old": before, "new": after}
        for _, _, found, name, before, after in sorted(examples)[:LISTED]
    ]


def compare_archives(old_zip: Path, new_zip: Path) -> ComparisonResult:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        old_dir = _extract(old_zip, tmp_path / "old")
        new_dir = _extract(new_zip, tmp_path / "new")

        result = ComparisonResult(eml_differs=_compare_eml(old_dir, new_dir))

        old_tables = {t.file_location: t for t in validate.parse_meta_xml(old_dir / "meta.xml")}
        new_tables = {t.file_location: t for t in validate.parse_meta_xml(new_dir / "meta.xml")}
        result.tables_added = sorted(set(new_tables) - set(old_tables))
        result.tables_removed = sorted(set(old_tables) - set(new_tables))
        result.undeclared_in_old = _undeclared_members(old_zip, set(old_tables))
        result.undeclared_in_new = _undeclared_members(new_zip, set(new_tables))
        for file_location in sorted(set(old_tables) & set(new_tables)):
            table = old_tables[file_location]
            header = read_header(old_dir / file_location, delimiter="\t")
            id_column = header[table.id_index]
            result.tables.append(
                _compare_table(
                    file_location.rsplit(".", 1)[0], old_dir, new_dir, file_location, id_column
                )
            )
    return result


def render_summary_markdown(result: ComparisonResult) -> str:
    lines = ["# Archive comparison", ""]
    if not result.diverged:
        lines.append("No differences.")
        return "\n".join(lines) + "\n"

    if result.eml_differs:
        lines.append("- `eml.xml` differs (beyond `packageId`).")
    for table in result.tables_added:
        lines.append(f"- `{table}` is present in the new archive only.")
    for table in result.tables_removed:
        lines.append(f"- `{table}` is present in the old archive only.")
    for side, members in (("old", result.undeclared_in_old), ("new", result.undeclared_in_new)):
        lines += [
            f"- `{name}` is in the {side} zip, but its meta.xml doesn't declare it."
            for name in members
        ]
    for t in result.tables:
        if not t.diverged:
            continue
        lines.append(f"## {t.table}")
        if t.columns_added:
            lines.append(f"- Columns added: {', '.join(t.columns_added)}")
        if t.columns_removed:
            lines.append(f"- Columns removed: {', '.join(t.columns_removed)}")
        if not t.row_order_matches:
            lines.append("- Row order differs.")
        if t.rows_only_in_old:
            lines.append(f"- {t.rows_only_in_old} row(s) only in the old archive")
        if t.rows_only_in_new:
            lines.append(f"- {t.rows_only_in_new} row(s) only in the new archive")
        for name, count in sorted(t.value_diff_counts.items()):
            lines.append(f"- {count} value difference(s) in `{name}`")
        if t.value_examples:
            lines.append("")
            lines.append("Examples:")
            for example in t.value_examples:
                lines.append(
                    f"- `{example['id']}` / `{example['column']}`: "
                    f"{example['old']!r} -> {example['new']!r}"
                )
        lines.append("")
    return "\n".join(lines) + "\n"


def archive_digest(archive_zip: Path) -> str:
    return hashlib.sha256(archive_zip.read_bytes()).hexdigest()


def write_comparison(result: ComparisonResult, out_path: Path) -> None:
    out_path.write_text(render_summary_markdown(result), encoding="utf-8")
    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
