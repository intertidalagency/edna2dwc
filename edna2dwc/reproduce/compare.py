from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import tempfile
import zipfile



@dataclass
class TableDiff:
    table: str
    columns_added: list[str] = field(default_factory=list)
    columns_removed: list[str] = field(default_factory=list)
    value_examples: list[dict] = field(default_factory=list)
    only_in_new: list[str] = field(default_factory=list)
    row_order_matches: bool = True

    @property
    def diverged(self) -> bool:
        return bool(
            self.columns_added
            or self.columns_removed
            or self.value_diff_counts
            or not self.row_order_matches
        )


@dataclass
class ComparisonResult:
    tables: list[TableDiff] = field(default_factory=list)
    eml_differs: bool = False

    @property
    def diverged(self) -> bool:

    def to_dict(self) -> dict:
        return {
            "diverged": self.diverged,
            "eml_differs": self.eml_differs,
            "tables": [
                {
                    "table": t.table,
                    "columns_added": t.columns_added,
                    "columns_removed": t.columns_removed,
                    "value_diff_counts": t.value_diff_counts,
                    "value_examples": t.value_examples,
                    "only_in_old": t.only_in_old,
                    "only_in_new": t.only_in_new,
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


def _compare_eml(old_dir: Path, new_dir: Path) -> bool:


def _compare_table(
    table_name: str, old_dir: Path, new_dir: Path, file_location: str, id_column: str
) -> TableDiff:
    diff = TableDiff(table=table_name)
    old_header = read_header(old_dir / file_location, delimiter="\t")
    new_header = read_header(new_dir / file_location, delimiter="\t")
    diff.columns_added = [c for c in new_header if c not in old_header]
    diff.columns_removed = [c for c in old_header if c not in new_header]
    return diff


def compare_archives(old_zip: Path, new_zip: Path) -> ComparisonResult:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        old_dir = _extract(old_zip, tmp_path / "old")
        new_dir = _extract(new_zip, tmp_path / "new")

        result = ComparisonResult(eml_differs=_compare_eml(old_dir, new_dir))

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
        return "\n".join(lines) + "\n"

    if result.eml_differs:
        lines.append("- `eml.xml` differs (beyond `packageId`).")
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


def write_comparison(result: ComparisonResult, out_path: Path) -> None:
    out_path.write_text(render_summary_markdown(result), encoding="utf-8")
    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
