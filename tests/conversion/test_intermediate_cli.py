import json


def test_validate_intermediate_succeeds_on_a_valid_file(run_cli, tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text("sampleID\tfeatureID\tcount\ttaxonomy\ns1\tf1\t10\td__Bacteria\n")

    result = run_cli(["validate-intermediate", str(path)])

    assert result.exit_code == 0
    assert result.render() == f"OK: {path} satisfies the intermediate table's schema."


def test_validate_intermediate_fails_and_reports_each_finding(run_cli, tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text("featureID\tcount\ttaxonomy\nf1\t10\td__Bacteria\n")

    result = run_cli(["validate-intermediate", str(path), "--json"])

    assert result.exit_code == 1
    assert result.text.endswith("\n\n1 finding(s).")
    payload = json.loads(result.render())
    assert payload["command"] == "validate-intermediate"
    assert payload["status"] == "error"
    assert payload["decision"] is None
    assert [(f["code"], f["severity"]) for f in payload["findings"]] == [
        ("CONTRACT_COLUMN_MISSING", "error")
    ]
