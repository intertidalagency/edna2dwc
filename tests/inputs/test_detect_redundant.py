from __future__ import annotations

import pytest

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


    lines = ["a\tcount"]
    lines.append("a\t1")
    lines.append("bb\t2")
    lines.extend(f"x\t{i}" for i in range(3, 21))
    lines.append("y\tabc")
    fp = fingerprint_file(path)
    assert fp.n_rows == 22


    path = _write(tmp_path, "ambiguous.tsv", "a\nb\n")
    fp = fingerprint_file(path)
    assert fp.n_rows == 1






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


def test_raises_when_every_single_file_fails_to_fingerprint(tmp_path):
    a_directory = tmp_path / "not_a_file.tsv"
    a_directory.mkdir()
        detect_redundant_paths([a_directory])


def test_empty_paths_list_does_not_raise():
    report = detect_redundant_paths([])
    assert report.fingerprints == {}
    assert report.verdicts == {}
