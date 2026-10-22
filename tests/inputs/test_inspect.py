from __future__ import annotations

import gzip
import zipfile

import pytest

from edna2dwc.common.tsv import SAMPLE_BYTES
from edna2dwc.inputs.inspect import inspect_path
from tests.inputs.test_document_text import write_docx
from tests.paths import INPUT_FIXTURES

FIXTURES = INPUT_FIXTURES


def test_xlsx_reports_sheet_names():
    report = inspect_path(FIXTURES / "sample.xlsx")
    assert report.format == "xlsx"
    sheet_names = [s["name"] for s in report.summary["sheets"]]
    assert sheet_names == ["Table 1", "ASV counts"]


def test_xlsx_preview_reads_inline_string_and_numeric_cells():
    report = inspect_path(FIXTURES / "sample.xlsx")
    table1 = report.summary["sheets"][0]
    assert table1["max_row"] == 3
    assert table1["max_col"] == 4
    preview = table1["preview_first_5_rows"]
    assert preview[0] == ["Station #", "Lat (ddmm.mmm)", "Lon (ddmm.mmm)", "Date"]
    assert preview[1][0] == "STA1"
    assert preview[1][1] == "4530.5"


def test_qza_lists_namelist_and_previews_action_yaml_and_tsv_data():
    report = inspect_path(FIXTURES / "sample.qza")
    assert report.format == "qza"
    names = [entry["name"] for entry in report.summary["namelist"]]
    assert any(name.endswith("action.yaml") for name in names)
    assert "dada2" in report.summary["first_action_yaml_preview"]
    (tsv_preview,) = report.summary["data_file_previews"].values()
    assert tsv_preview.startswith("Feature ID\tTaxon\tConfidence")


def test_a_zip_without_a_qiime_metadata_yaml_is_not_labelled_qza(tmp_path):
    path = tmp_path / "supplement.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("supplement/counts.tsv", "sampleID\tcount\nS1\t3\n")
    report = inspect_path(path)
    assert report.format == "zip"
    assert [entry["name"] for entry in report.summary["namelist"]] == ["supplement/counts.tsv"]


def test_a_zip_holding_a_qiime_metadata_yaml_is_labelled_qza(tmp_path):
    path = tmp_path / "table.zip"
    path.write_bytes((FIXTURES / "sample.qza").read_bytes())
    assert inspect_path(path).format == "qza"


def test_biom_json_v1_reports_shape_and_id_previews():
    report = inspect_path(FIXTURES / "sample_v1.biom")
    assert report.format == "biom-json-v1"
    assert report.summary["shape"] == [2, 2]
    assert report.summary["first_3_rows"][0]["id"] == "asv1"


def test_biom_hdf5_reports_shape_and_id_previews():
    report = inspect_path(FIXTURES / "sample_v2.biom")
    assert report.format == "biom-hdf5"
    assert "h5py" in report.notes[0]
    assert report.summary["shape"] == [2, 2]
    assert report.summary["first_3_rows"][0]["id"] == "asv1"
    assert isinstance(report.summary["first_3_rows"][0]["taxonomy"], str)
    assert report.summary["first_3_columns"][0]["id"] == "S001"


def test_delimited_detects_tab_and_previews_rows():
    report = inspect_path(FIXTURES / "sample.tsv")
    assert report.format == "delimited"
    assert report.summary["delimiter"] == "\t"
    assert report.summary["header"] == ["sampleID", "featureID", "count", "taxonomy"]


def test_unrecognized_text_previews_unrecognized_text_file():
    report = inspect_path(FIXTURES / "custom_export.lims")
    assert report.format == "unrecognized-text"
    assert "LIMS" in report.summary["text_preview"]
    assert report.notes
    assert "write" not in " ".join(report.notes).lower()


PROSE = (
    "Methods\n\nWater samples were filtered through 0.22 um membranes.\n"
    "Primers: mlCOIintF / jgHCO2198. Annealing at 46 C.\n"
)


def test_a_prose_txt_is_a_document_not_a_table(tmp_path):
    path = tmp_path / "methods.txt"
    path.write_text(PROSE)
    report = inspect_path(path)
    assert report.format == "document"
    assert report.summary["text_preview"].startswith("Methods")


def test_a_delimited_txt_larger_than_the_sample_is_still_a_table(tmp_path):
    path = tmp_path / "counts.txt"
    rows = "".join(f"s{i}\tfeature_{i}_with_a_longish_name\t{i}\n" for i in range(20_000))
    path.write_text(f"sampleID\tfeatureID\tcount\n{rows}")
    assert path.stat().st_size > SAMPLE_BYTES
    report = inspect_path(path)
    assert report.format == "delimited"
    assert report.summary["header"] == ["sampleID", "featureID", "count"]


def test_a_gzipped_prose_txt_is_a_document_with_a_preview(tmp_path):
    path = tmp_path / "methods.txt.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(PROSE)
    report = inspect_path(path)
    assert report.format == "document"
    assert report.summary["text_preview"].startswith("Methods")


def test_a_txt_that_is_not_utf8_is_a_document_without_a_preview(tmp_path):
    path = tmp_path / "methods.txt"
    path.write_bytes(b"M\xe9thodes: filtr\xe9 sur membrane\n")
    report = inspect_path(path)
    assert report.format == "document"
    assert report.summary == {}


@pytest.mark.parametrize("name", ["README.md", "methods.pdf", "protocol.docx"])
def test_documents_are_reported_as_documents_without_a_preview_of_binary(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4 \xff\xfe not text" if name != "README.md" else PROSE.encode())
    report = inspect_path(path)
    assert report.format == "document"
    assert "hex_preview" not in report.summary


def test_a_docx_previews_its_text(tmp_path):
    path = tmp_path / "protocol.docx"
    write_docx(path, "Primers: MiFish-U")
    assert inspect_path(path).summary["text_preview"] == "Primers: MiFish-U\n"


def test_unrecognized_binary_previews_hex_for_undecodable_bytes():
    report = inspect_path(FIXTURES / "custom_export.bin")
    assert report.format == "unrecognized-binary"
    assert report.summary["hex_preview"].startswith("fffe0001")


def test_rds_reports_rscript_availability_without_reading_content(tmp_path):
    rds_path = tmp_path / "phyloseq_obj.rds"
    rds_path.write_bytes(b"not a real rds file")
    report = inspect_path(rds_path)
    assert report.format == "rds"
    assert isinstance(report.summary["rscript_available"], bool)


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*")))
def test_every_ingest_fixture_inspects_without_raising(path):
    inspect_path(path)


def test_a_gzipped_csv_is_inspected_as_delimited(tmp_path):
    path = tmp_path / "counts.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("sampleID,featureID,count\ns1,f1,3\n")

    report = inspect_path(path)
    assert report.format == "delimited"
    assert report.summary["header"] == ["sampleID", "featureID", "count"]


def test_a_gzipped_file_that_is_not_delimited_is_reported_as_unrecognized(tmp_path):
    path = tmp_path / "table.biom.gz"
    with gzip.open(path, "wb") as f:
        f.write(b'{"id": "x", "format": "Biological Observation Matrix 1.0"}')

    report = inspect_path(path)
    assert report.format.startswith("unrecognized")
