from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import zipfile


TEXT_PREVIEW_CHARS = 2000
HEX_PREVIEW_BYTES = 64
XLSX_PREVIEW_ROWS = 5

_XLSX_EXTS = {".xlsx", ".xlsm"}


@dataclass
class InspectReport:
    path: str
    format: str
    summary: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "format": self.format,
            "summary": self.summary,
            "notes": self.notes,
        }


def inspect_path(path: Path) -> InspectReport:
    if suffix in _XLSX_EXTS:
        return _inspect_xlsx(path)
    if suffix == ".biom":
        return _inspect_biom(path)
        return _inspect_delimited(path)
    if suffix == ".rds":
        return _inspect_rds(path)
    return _inspect_unrecognized_format(path)


def _inspect_xlsx(path: Path) -> InspectReport:

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheets_summary = [_xlsx_sheet_summary(workbook[name]) for name in workbook.sheetnames]
    finally:
        workbook.close()
    return InspectReport(
        path=str(path),
        format="xlsx",
        summary={"sheets": sheets_summary},
        notes=[
            "Headers may be several rows down, not necessarily row 1.",
            "The table may be transposed relative to what its sheet name suggests.",
        ],
    )


def _xlsx_sheet_summary(worksheet) -> dict:
    preview: list[list[str]] = []
    for row in worksheet.iter_rows(values_only=True):
        if len(preview) >= XLSX_PREVIEW_ROWS:
            break
        if any(cell is not None for cell in row):
            preview.append(["" if cell is None else str(cell) for cell in row])
    return {
        "name": worksheet.title,
        "max_row": worksheet.max_row or 0,
        "max_col": worksheet.max_column or 0,
        f"preview_first_{XLSX_PREVIEW_ROWS}_rows": preview,
    }


    with zipfile.ZipFile(path) as zf:
        namelist = [{"name": info.filename, "size": info.file_size} for info in zf.infolist()]
    return InspectReport(
        path=str(path),
        format="qza",
        summary={
            "namelist": namelist,
            "metadata_yaml_preview": metadata_preview,
            "first_action_yaml_preview": action_preview,
            "data_file_previews": data_previews,
        },
    )


def _depth_limited_yaml_preview(text: str, max_depth: int = 2) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if indent // 2 >= max_depth and stripped.startswith(("-", " ")) is False:
            continue
        if indent // 2 < max_depth:
            lines.append(line)
    return "\n".join(lines)


_HDF5_MAGIC = b"\x89HDF"


def _inspect_biom(path: Path) -> InspectReport:
    with path.open("rb") as f:
        magic = f.read(len(_HDF5_MAGIC))
    if magic == _HDF5_MAGIC:
        return _inspect_biom_hdf5(path)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    shape = data.get("shape")
    rows = data.get("rows", [])[:3]
    columns = data.get("columns", [])[:3]
    return InspectReport(
        path=str(path),
        format="biom-json-v1",
        summary={
            "biom_format": data.get("format", "unknown"),
            "shape": shape,
            "first_3_rows": rows,
            "first_3_columns": columns,
        },
    )


def _inspect_biom_hdf5(path: Path) -> InspectReport:

    with h5py.File(path, "r") as f:
        obs = f["observation"]
        obs_ids = [_hdf5_decode(v) for v in obs["ids"][:]]
        sample_ids = [_hdf5_decode(v) for v in f["sample"]["ids"][:]]
        rows = [
            {"id": obs_id, "taxonomy": _hdf5_taxonomy(obs, i)}
            for i, obs_id in enumerate(obs_ids[:3])
        ]
        columns = [{"id": sample_id} for sample_id in sample_ids[:3]]
    return InspectReport(
        path=str(path),
        format="biom-hdf5",
        summary={
            "biom_version": "2.x (HDF5)",
            "shape": [len(obs_ids), len(sample_ids)],
            "first_3_rows": rows,
            "first_3_columns": columns,
        },
    )


def _hdf5_decode(value) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _hdf5_taxonomy(obs_group, index: int) -> str:
    metadata = obs_group.get("metadata")
    if metadata is None or "taxonomy" not in metadata:
        return ""
    ranks = metadata["taxonomy"][index]
    return ";".join(_hdf5_decode(r) for r in ranks if _hdf5_decode(r))


def _inspect_delimited(path: Path) -> InspectReport:
    lines = sample.splitlines()
    header = lines[0] if lines else ""
    preview_rows = lines[1:6]
    return InspectReport(
        path=str(path),
        format="delimited",
        summary={
            "delimiter": delimiter,
            "header": header.split(delimiter) if header else [],
            "preview_rows": [row.split(delimiter) for row in preview_rows],
        },
    )


def _inspect_rds(path: Path) -> InspectReport:
    rscript = shutil.which("Rscript")
    return InspectReport(
        path=str(path),
        format="rds",
        summary={"rscript_available": rscript is not None},
        notes=[
        ],
    )


def _unrecognized_format_note(kind: str) -> str:
    return (
    )


def _inspect_unrecognized_format(path: Path) -> InspectReport:
    try:
        with path.open(encoding="utf-8", errors="strict") as f:
            text = f.read(TEXT_PREVIEW_CHARS)
        return InspectReport(
            path=str(path),
            format="unrecognized-text",
            summary={"text_preview": text},
            notes=[_unrecognized_format_note("format")],
        )
    except UnicodeDecodeError:
        with path.open("rb") as f:
            raw = f.read(HEX_PREVIEW_BYTES)
        return InspectReport(
            path=str(path),
            format="unrecognized-binary",
            summary={"hex_preview": raw.hex()},
            notes=[_unrecognized_format_note("binary format")],
        )
