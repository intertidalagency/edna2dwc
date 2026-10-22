from __future__ import annotations

import pytest




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


def test_biom_json_v1_reports_shape_and_id_previews():
    report = inspect_path(FIXTURES / "sample_v1.biom")
    assert report.format == "biom-json-v1"
    assert report.summary["shape"] == [2, 2]
    assert report.summary["first_3_rows"][0]["id"] == "asv1"


def test_biom_hdf5_reports_shape_and_id_previews():
    report = inspect_path(FIXTURES / "sample_v2.biom")
    assert report.format == "biom-hdf5"
    assert report.summary["shape"] == [2, 2]
    assert report.summary["first_3_rows"][0]["id"] == "asv1"
    assert isinstance(report.summary["first_3_rows"][0]["taxonomy"], str)
    assert report.summary["first_3_columns"][0]["id"] == "S001"


    report = inspect_path(FIXTURES / "sample.tsv")
    assert report.format == "delimited"
    assert report.summary["delimiter"] == "\t"
    assert report.summary["header"] == ["sampleID", "featureID", "count", "taxonomy"]


def test_unrecognized_text_previews_unrecognized_text_file():
    report = inspect_path(FIXTURES / "custom_export.lims")
    assert report.format == "unrecognized-text"
    assert "LIMS" in report.summary["text_preview"]


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
    inspect_path(path)
