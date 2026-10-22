import gzip
import json

import pytest

from edna2dwc.common.tsv import (
    NotTabSeparatedError,
    detect_delimiter,
    read_header,
    read_rows,
    read_tab_separated_rows,
    write_tsv,
)


@pytest.mark.parametrize("bom", [b"\xef\xbb\xbf", b""])
def test_a_bom_is_stripped_from_the_first_header_cell(tmp_path, bom):
    path = tmp_path / "header.tsv"
    path.write_bytes(bom + b"sampleID\tfeatureID\ns1\tf1\n")

    assert read_header(path) == ["sampleID", "featureID"]


@pytest.mark.parametrize(
    ("text", "delimiter"),
    [
        ("sampleID\tfeatureID\ns1\tf1\n", "\t"),
        ("sampleID,featureID\ns1,f1\n", ","),
        ("onlyonecolumn\nvalue\n", "\t"),
    ],
)
def test_detect_delimiter_prefers_a_tab_when_the_text_does_not_say(text, delimiter):
    assert detect_delimiter(text) == delimiter


def test_a_tab_separated_row_whose_cell_holds_json_is_read_as_tab_separated():
    remarks = json.dumps({f"remark_{k}": f"bottle {k} at station 3" for k in range(10)})
    text = "sampleID\teventID\tdynamicProperties\nS1\tE1\t" + remarks + "\n"

    assert detect_delimiter(text) == "\t"


def test_read_rows_yields_header_keyed_dicts(tmp_path):
    path = tmp_path / "data.tsv"
    path.write_text("sampleID\tfeatureID\ns1\tf1\ns2\tf2\n")

    rows = list(read_rows(path))
    assert rows == [
        {"sampleID": "s1", "featureID": "f1"},
        {"sampleID": "s2", "featureID": "f2"},
    ]


def test_read_rows_accepts_an_explicit_delimiter(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("sampleID,featureID\ns1,f1\n")

    rows = list(read_rows(path, delimiter=","))
    assert rows == [{"sampleID": "s1", "featureID": "f1"}]


def test_a_field_larger_than_the_stdlib_limit_is_read_whole(tmp_path):
    big_value = "x" * (131072 + 50000)
    path = tmp_path / "big_field.tsv"
    path.write_text(f"sampleID\tdynamicProperties\ns1\t{big_value}\n")

    rows = list(read_rows(path))
    assert len(rows[0]["dynamicProperties"]) == len(big_value)


def test_write_tsv_truncates_a_preexisting_file_for_no_rows_and_no_columns(tmp_path):
    out_path = tmp_path / "empty.tsv"
    out_path.write_text("stale\tcontent\n", encoding="utf-8")
    write_tsv([], out_path)
    assert out_path.read_text(encoding="utf-8") == ""


def test_write_tsv_still_writes_an_explicit_header_for_no_rows(tmp_path):
    out_path = tmp_path / "report.tsv"
    write_tsv([], out_path, columns=["sampleID", "reason"])
    assert out_path.read_text(encoding="utf-8") == "sampleID\treason\n"


def test_write_tsv_creates_the_directory_the_caller_named(tmp_path):
    out_path = tmp_path / "nested" / "dir" / "lineage.tsv"
    write_tsv([{"a": "1"}], out_path)
    assert out_path.read_text(encoding="utf-8") == "a\n1\n"


def test_write_tsv_creates_the_directory_for_an_empty_file(tmp_path):
    out_path = tmp_path / "nested" / "empty.tsv"
    write_tsv([], out_path)
    assert out_path.read_text(encoding="utf-8") == ""


def test_a_gzipped_delimited_file_reads_like_a_plain_one(tmp_path):
    path = tmp_path / "table.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("sampleID,featureID\ns1,f1\n")

    assert read_header(path) == ["sampleID", "featureID"]
    assert list(read_rows(path)) == [{"sampleID": "s1", "featureID": "f1"}]


def test_read_tab_separated_rows_rejects_a_comma_separated_file(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text("sampleID,featureID,count\ns1,f1,10\n")
    with pytest.raises(NotTabSeparatedError, match="must be tab-separated") as raised:
        list(read_tab_separated_rows(path))
    assert str(path) in str(raised.value)


def test_read_tab_separated_rows_reads_an_empty_file_as_no_rows(tmp_path):
    path = tmp_path / "lineage.tsv"
    path.write_text("")
    assert list(read_tab_separated_rows(path)) == []


def test_read_tab_separated_rows_reads_a_one_column_table(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text("sampleID\ns1\n")
    assert list(read_tab_separated_rows(path)) == [{"sampleID": "s1"}]
