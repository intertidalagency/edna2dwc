from __future__ import annotations

import gzip

import pytest

from edna2dwc.inputs.detect_redundant import (
    Fingerprint,
    detect_redundant_paths,
    fingerprint_file,
    verdict,
)


def _write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_fingerprint_counts_rows_and_sums_numeric_cells(tmp_path):
    path = _write(tmp_path, "a.tsv", "f1\t10\t5\nf2\t3\t0\n")
    fp = fingerprint_file(path)
    assert fp.n_rows == 2
    assert fp.n_distinct_ids == 2
    assert fp.total == pytest.approx(18.0)


def test_fingerprint_is_order_independent(tmp_path):
    forward = _write(tmp_path, "forward.tsv", "f1\t10\nf2\t20\nf3\t30\n")
    reverse = _write(tmp_path, "reverse.tsv", "f3\t30\nf2\t20\nf1\t10\n")
    assert fingerprint_file(forward) == fingerprint_file(reverse)


def test_fingerprint_dedupes_repeated_ids_within_one_file(tmp_path):
    path = _write(tmp_path, "dup.tsv", "f1\t10\nf1\t10\nf2\t20\n")
    fp = fingerprint_file(path)
    assert fp.n_distinct_ids == 2


@pytest.mark.parametrize("text", ["", "f1\t0\nf2\t0\n"])
def test_a_file_with_no_counts_is_blank(tmp_path, text):
    assert fingerprint_file(_write(tmp_path, "blank.tsv", text)).is_blank


def test_fingerprint_excludes_the_header_row(tmp_path):
    a = _write(tmp_path, "a.tsv", "featureID\tS1\tS2\nf1\t10\t5\nf2\t3\t0\n")
    b = _write(tmp_path, "b.tsv", "#OTU ID\tS1\tS2\nf1\t10\t5\nf2\t3\t0\n")
    assert fingerprint_file(a) == fingerprint_file(b)


def test_fingerprint_header_exclusion_does_not_drop_a_real_headerless_first_row(tmp_path):
    path = _write(tmp_path, "headerless.tsv", "f1\t10\t5\nf2\t3\t0\n")
    fp = fingerprint_file(path)
    assert fp.n_rows == 2
    assert fp.total == pytest.approx(18.0)


def test_fingerprint_a_single_row_file_defaults_to_headerless(tmp_path):
    path = _write(tmp_path, "one_row.tsv", "f1\t10\t5\n")
    fp = fingerprint_file(path)
    assert fp.n_rows == 1
    assert fp.total == pytest.approx(15.0)


def test_fingerprint_header_check_uses_every_row_has_header_can_vote_on(tmp_path):
    lines = ["a\tcount"]
    lines.append("a\t1")
    lines.append("bb\t2")
    lines.extend(f"x\t{i}" for i in range(3, 21))
    lines.append("y\tabc")
    assert len(lines) == 22
    path = _write(tmp_path, "header_check_boundary.tsv", "\n".join(lines) + "\n")
    fp = fingerprint_file(path)
    assert fp.n_rows == 22


def test_fingerprint_excludes_the_first_row_when_the_header_check_itself_fails(tmp_path):
    path = _write(tmp_path, "ambiguous.tsv", "a\nb\n")
    fp = fingerprint_file(path)
    assert fp.n_rows == 1


TWO_IDS = Fingerprint(n_rows=2, n_distinct_ids=2, xor_hash=123, total=15.0)


@pytest.mark.parametrize(
    ("other", "expected"),
    [
        (
            Fingerprint(n_rows=2, n_distinct_ids=2, xor_hash=123, total=15.0000001),
            "likely redundant",
        ),
        (
            Fingerprint(n_rows=2, n_distinct_ids=2, xor_hash=123, total=1.5),
            "raw vs. normalized, not redundant",
        ),
        (Fingerprint(n_rows=3, n_distinct_ids=3, xor_hash=456, total=15.0), "coincidental"),
        (Fingerprint(n_rows=5, n_distinct_ids=5, xor_hash=789, total=99.0), "distinct"),
        (Fingerprint(n_rows=0, n_distinct_ids=0, xor_hash=0, total=0.0), "blank"),
    ],
)
def test_verdict_compares_the_ids_and_totals_of_two_fingerprints(other, expected):
    assert verdict(TWO_IDS, other) == expected


def test_verdict_respects_a_wider_tolerance_override():
    a = Fingerprint(n_rows=2, n_distinct_ids=2, xor_hash=123, total=100.0)
    b = Fingerprint(n_rows=2, n_distinct_ids=2, xor_hash=123, total=100.5)
    assert verdict(a, b) == "raw vs. normalized, not redundant"
    assert verdict(a, b, tolerance=0.01) == "likely redundant"


def test_end_to_end_two_identical_tables_are_likely_redundant(tmp_path):
    original = _write(tmp_path, "original.tsv", "f1\t10\nf2\t20\n")
    duplicate = _write(tmp_path, "duplicate.tsv", "f1\t10\nf2\t20\n")
    report = detect_redundant_paths([original, duplicate])
    (verdict_value,) = report.verdicts.values()
    assert verdict_value == "likely redundant"


def test_unreadable_file_is_a_failure_not_a_crash(tmp_path):
    good = _write(tmp_path, "good.tsv", "f1\t10\n")
    a_directory = tmp_path / "actually_a_dir.tsv"
    a_directory.mkdir()
    report = detect_redundant_paths([good, a_directory])
    assert str(a_directory) in report.failures
    assert str(good) in report.fingerprints


def test_a_gzipped_table_is_fingerprinted_like_its_plain_copy(tmp_path):
    plain = _write(tmp_path, "counts.tsv", "f1\t10\nf2\t20\n")
    zipped = tmp_path / "counts.tsv.gz"
    zipped.write_bytes(gzip.compress(plain.read_bytes()))
    report = detect_redundant_paths([plain, zipped])
    assert not report.failures
    assert report.verdicts == {(str(plain), str(zipped)): "likely redundant"}


def test_raises_when_every_single_file_fails_to_fingerprint(tmp_path):
    a_directory = tmp_path / "not_a_file.tsv"
    a_directory.mkdir()
    with pytest.raises(ValueError):
        detect_redundant_paths([a_directory])


def test_empty_paths_list_does_not_raise():
    report = detect_redundant_paths([])
    assert report.fingerprints == {}
    assert report.verdicts == {}
