import json


def test_detect_redundant_reports_each_pair_and_each_fingerprint(run_cli, tmp_path):
    original = tmp_path / "original.tsv"
    duplicate = tmp_path / "duplicate.tsv"
    original.write_text("f1\t10\nf2\t20\n")
    duplicate.write_text("f1\t10\nf2\t20\n")

    result = run_cli(["detect-redundant", "--json", str(original), str(duplicate)])

    assert result.exit_code == 0
    assert result.text == f"{original} vs {duplicate}: likely redundant"
    assert sorted(json.loads(result.render())["fingerprints"]) == sorted(
        [str(original), str(duplicate)]
    )
