from __future__ import annotations

import csv
from pathlib import Path

import pytest

from edna2dwc.common import table
from edna2dwc.inputs.assemble import AssembleError, Sources, assemble


def _write(path: Path, rows: list[list[str]], delimiter: str = ",") -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f, delimiter=delimiter).writerows(rows)
    return path


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _codes(result) -> list[str]:
    return [f.code for f in result.findings.findings]


@pytest.fixture
def wide(tmp_path) -> Path:
    return _write(
        tmp_path / "counts.csv",
        [["featureID", "S1", "S2"], ["asv1", "5", "0"], ["asv2", "", "3"]],
    )


def test_a_wide_count_table_becomes_one_row_per_nonzero_cell(tmp_path, wide):
    out = tmp_path / "occurrence_long.tsv"
    result = assemble(Sources(counts=(wide,)), out)

    rows = _read(out)
    assert [(r["sampleID"], r["featureID"], r["count"]) for r in rows] == [
        ("S1", "asv1", "5"),
        ("S2", "asv2", "3"),
    ]
    assert result.rows == 2
    assert list(rows[0])[:3] == ["sampleID", "featureID", "count"]
    (dropped,) = [f for f in result.findings.findings if f.code == "PRESENCE_ONLY_FILTERED"]
    assert dropped.count == 2


def test_a_wide_count_table_of_thousands_of_samples_is_read_within_the_memory_limit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(table.MEMORY_LIMIT_ENV, "256MB")
    samples, features = 5000, 200
    counts = _write(
        tmp_path / "counts.csv",
        [
            ["featureID", *(f"S{i}" for i in range(samples))],
            *(
                [
                    f"asv{row}",
                    *("1" if i in (row, samples - 1 - row) else "0" for i in range(samples)),
                ]
                for row in range(features)
            ),
        ],
    )
    out = tmp_path / "occurrence_long.tsv"

    result = assemble(Sources(counts=(counts,)), out)

    assert [(r["featureID"], r["sampleID"]) for r in _read(out)] == [
        (f"asv{row}", f"S{i}") for row in range(features) for i in (row, samples - 1 - row)
    ]
    (dropped,) = [f for f in result.findings.findings if f.code == "PRESENCE_ONLY_FILTERED"]
    assert dropped.count == features * (samples - 2)


def test_keep_zeros_keeps_the_zero_cells_of_a_wide_table(tmp_path, wide):
    out = tmp_path / "occurrence_long.tsv"
    assemble(Sources(counts=(wide,), keep_zeros=True), out)
    assert ("S2", "asv1", "0") in [(r["sampleID"], r["featureID"], r["count"]) for r in _read(out)]


def test_a_long_count_table_passes_through_with_its_other_columns(tmp_path):
    counts = _write(
        tmp_path / "long.tsv",
        [["sampleID", "featureID", "count", "marker"], ["S1", "asv1", "4", "COI"]],
        delimiter="\t",
    )
    out = tmp_path / "occurrence_long.tsv"
    assemble(Sources(counts=(counts,)), out)
    assert _read(out) == [{"sampleID": "S1", "featureID": "asv1", "count": "4", "marker": "COI"}]


@pytest.fixture
def long(tmp_path) -> Path:
    return _write(
        tmp_path / "long.tsv",
        [["sampleID", "featureID", "count"], ["S1", "asv1", "4"], ["S1", "asv2", "0"]],
        delimiter="\t",
    )


def test_a_long_count_table_drops_its_zero_counts(tmp_path, long):
    out = tmp_path / "occurrence_long.tsv"
    result = assemble(Sources(counts=(long,)), out)
    assert [r["featureID"] for r in _read(out)] == ["asv1"]
    (dropped,) = [f for f in result.findings.findings if f.code == "PRESENCE_ONLY_FILTERED"]
    assert dropped.count == 1


def test_keep_zeros_keeps_the_zero_counts_of_a_long_table(tmp_path, long):
    out = tmp_path / "occurrence_long.tsv"
    result = assemble(Sources(counts=(long,), keep_zeros=True), out)
    assert [r["featureID"] for r in _read(out)] == ["asv1", "asv2"]
    assert "PRESENCE_ONLY_FILTERED" not in _codes(result)


def test_a_sample_column_that_holds_text_is_refused(tmp_path):
    counts = _write(
        tmp_path / "counts.csv", [["featureID", "S1", "taxon"], ["asv1", "5", "Gadus"]]
    )
    with pytest.raises(AssembleError, match="taxon"):
        assemble(Sources(counts=(counts,)), tmp_path / "out.tsv")


def test_features_samples_and_sequences_join_on_their_keys(tmp_path, wide):
    features = _write(
        tmp_path / "taxonomy.csv",
        [["featureID", "taxonomy"], ["asv1", "Animalia;Chordata"], ["asv2", "Bacteria"]],
    )
    samples = _write(
        tmp_path / "samples.csv",
        [["sampleID", "eventDate"], ["S1", "2022-01-28"], ["S2", "2022-01-29"]],
    )
    fasta = tmp_path / "asvs.fasta"
    fasta.write_text(">asv1 desc\nACGT\nTT\n>asv2\nGGCC\n", encoding="utf-8")
    out = tmp_path / "occurrence_long.tsv"

    assemble(
        Sources(counts=(wide,), features=(features,), samples=(samples,), sequences=(fasta,)),
        out,
    )

    by_feature = {r["featureID"]: r for r in _read(out)}
    assert by_feature["asv1"]["taxonomy"] == "Animalia;Chordata"
    assert by_feature["asv1"]["sequence"] == "ACGTTT"
    assert by_feature["asv2"]["eventDate"] == "2022-01-29"


def test_a_key_with_no_counterpart_keeps_its_row_and_is_reported(tmp_path, wide):
    features = _write(tmp_path / "taxonomy.csv", [["featureID", "taxonomy"], ["asv1", "Bacteria"]])
    samples = _write(tmp_path / "samples.csv", [["sampleID", "site"], ["S1", "a"], ["S9", "b"]])
    out = tmp_path / "occurrence_long.tsv"

    result = assemble(Sources(counts=(wide,), features=(features,), samples=(samples,)), out)

    assert len(_read(out)) == 2
    unmatched = [
        f.message
        for f in result.findings.findings
        if f.code in ("JOIN_UNMATCHED", "JOIN_METADATA_MISSING")
    ]
    assert any("asv2" in m for m in unmatched)
    assert any("S2" in m for m in unmatched)
    assert any("S9" in m for m in unmatched)


def test_a_duplicate_key_in_a_lookup_table_is_refused(tmp_path, wide):
    features = _write(
        tmp_path / "taxonomy.csv",
        [["featureID", "taxonomy"], ["asv1", "Bacteria"], ["asv1", "Archaea"]],
    )
    with pytest.raises(AssembleError, match="asv1"):
        assemble(Sources(counts=(wide,), features=(features,)), tmp_path / "out.tsv")


def test_two_sample_tables_that_share_samples_are_told_to_join_them(tmp_path, wide):
    stations = _write(tmp_path / "stations.csv", [["sampleID", "site"], ["S1", "A"]])
    tracker = _write(tmp_path / "tracker.csv", [["sampleID", "depth"], ["S1", "5"]])
    with pytest.raises(AssembleError, match="join them into one --samples table"):
        assemble(Sources(counts=(wide,), samples=(stations, tracker)), tmp_path / "out.tsv")


def test_a_column_two_tables_both_give_is_refused(tmp_path):
    counts = _write(
        tmp_path / "long.csv",
        [["sampleID", "featureID", "count", "marker"], ["S1", "asv1", "4", "COI"]],
    )
    features = _write(tmp_path / "taxonomy.csv", [["featureID", "marker"], ["asv1", "12S"]])
    with pytest.raises(AssembleError, match="marker"):
        assemble(Sources(counts=(counts,), features=(features,)), tmp_path / "out.tsv")


def test_a_column_two_tables_both_give_names_both_tables(tmp_path, wide):
    features = _write(tmp_path / "taxonomy.csv", [["featureID", "sheet"], ["asv1", "A"]])
    samples = _write(tmp_path / "samples.csv", [["sampleID", "sheet"], ["S1", "B"]])
    with pytest.raises(AssembleError, match="both samples.csv and taxonomy.csv"):
        assemble(
            Sources(counts=(wide,), features=(features,), samples=(samples,)),
            tmp_path / "out.tsv",
        )


def test_a_fasta_id_with_two_sequences_is_refused(tmp_path, wide):
    fasta = tmp_path / "asvs.fasta"
    fasta.write_text(">asv1\nACGT\n>asv1\nTTTT\n", encoding="utf-8")
    with pytest.raises(AssembleError, match="asv1"):
        assemble(Sources(counts=(wide,), sequences=(fasta,)), tmp_path / "out.tsv")


def test_sequences_report_features_without_one(tmp_path, wide):
    fasta = tmp_path / "asvs.fasta"
    fasta.write_text(">asv1\nACGT\n>asv7\nTT\n", encoding="utf-8")
    result = assemble(Sources(counts=(wide,), sequences=(fasta,)), tmp_path / "out.tsv")
    messages = " ".join(f.message for f in result.findings.findings)
    assert "asv2" in messages
    assert "asv7" in messages


def test_count_tables_of_several_markers_are_stacked(tmp_path):
    first = _write(tmp_path / "coi.csv", [["featureID", "marker", "S1"], ["c1", "COI", "2"]])
    second = _write(tmp_path / "12s.csv", [["featureID", "marker", "S1"], ["m1", "12S", "7"]])
    out = tmp_path / "occurrence_long.tsv"
    assemble(Sources(counts=(first, second)), out)
    assert [(r["featureID"], r["marker"]) for r in _read(out)] == [("c1", "COI"), ("m1", "12S")]


def test_every_input_is_reported_with_its_rows_and_total(tmp_path, wide):
    result = assemble(Sources(counts=(wide,)), tmp_path / "out.tsv")
    (totals,) = [f for f in result.findings.findings if f.code == "INPUT_TOTALS"]
    assert "counts.csv" in totals.message
    assert "8" in totals.message


def test_a_count_table_with_no_feature_column_is_refused(tmp_path):
    counts = _write(tmp_path / "counts.csv", [["asv", "S1"], ["asv1", "5"]])
    with pytest.raises(AssembleError, match="featureID"):
        assemble(Sources(counts=(counts,)), tmp_path / "out.tsv")


def test_a_count_row_with_no_metadata_row_is_reported_apart_from_an_unused_lookup_row(
    tmp_path, wide
):
    features = _write(tmp_path / "taxonomy.csv", [["featureID", "taxonomy"], ["asv1", "Bacteria"]])
    samples = _write(tmp_path / "samples.csv", [["sampleID", "site"], ["S1", "a"], ["S9", "b"]])

    result = assemble(
        Sources(counts=(wide,), features=(features,), samples=(samples,)),
        tmp_path / "occurrence_long.tsv",
    )

    by_code: dict[str, list[str]] = {}
    for finding in result.findings.findings:
        by_code.setdefault(finding.code, []).append(finding.message)
    assert any("asv2" in m and "taxonomy.csv" in m for m in by_code["JOIN_METADATA_MISSING"])
    assert any("S2" in m and "samples.csv" in m for m in by_code["JOIN_METADATA_MISSING"])
    assert any("S9" in m for m in by_code["JOIN_UNMATCHED"])
    assert not any("S9" in m for m in by_code["JOIN_METADATA_MISSING"])


def test_a_table_with_no_rows_is_refused(tmp_path):
    counts = _write(tmp_path / "counts.csv", [["featureID", "S1", "S2"], ["asv1", "0", "0"]])
    with pytest.raises(AssembleError, match="no row"):
        assemble(Sources(counts=(counts,)), tmp_path / "occurrence_long.tsv")
