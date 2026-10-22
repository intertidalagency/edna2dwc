from __future__ import annotations

from collections.abc import Mapping
import json

import pytest
import yaml

from edna2dwc.cli.common import UsageError
from edna2dwc.common.tsv import write_tsv

METADATA = {
    "title": "Test dataset",
    "creators": [{"given": "J.", "surname": "Smith"}],
    "abstract": "A test abstract.",
    "license": "https://creativecommons.org/publicdomain/zero/1.0/",
    "contacts": [{"given": "Jane", "surname": "Smith"}],
    "pub_date": "2024-01-15",
}
CORE_ROW = {
    "occurrenceID": "ds1_s1_f1",
    "scientificName": "Mytilus californianus",
    "basisOfRecord": "MaterialSample",
}


def _package(
    run_cli, tmp_path, *, core_spec=None, core_row=CORE_ROW, metadata: Mapping = METADATA, extra=()
):
    core_path = tmp_path / "occurrence.tsv"
    write_tsv([core_row], core_path, columns=list(core_row))
    answers_path = tmp_path / "answers.yaml"
    answers_path.write_text(
        yaml.safe_dump(
            {
                "dataset_id": "urn-uuid-test",
                "created": "2024-06-01T00:00:00Z",
                "out_dir": "archive",
                "metadata": {
                    name: {"value": value, "provenance": name} for name, value in metadata.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return run_cli(
        [
            "package",
            "--core",
            core_spec or f"occurrence={core_path}",
            "--answers",
            str(answers_path),
            "-o",
            str(tmp_path / "archive"),
            *extra,
        ]
    )


def test_package_writes_an_archive_and_reports_where(run_cli, tmp_path):
    out_dir = tmp_path / "archive"
    result = _package(run_cli, tmp_path, extra=["--json"])
    assert result.exit_code == 0, result.render()
    assert result.text == f"Wrote archive to {out_dir} (dwca.zip)"
    assert json.loads(result.render())["outputs"] == {
        "archive_dir": str(out_dir),
        "zip": str(out_dir / "dwca.zip"),
        "measurements": [],
    }
    assert (out_dir / "dwca.zip").exists()


def test_package_reports_a_malformed_core_spec_as_a_usage_error(run_cli, tmp_path):
    with pytest.raises(UsageError) as error:
        _package(run_cli, tmp_path, core_spec="occ.tsv")
    assert str(error.value) == "--core 'occ.tsv' must be in TYPE=PATH form"


def test_package_reports_a_bad_column_as_a_usage_error(run_cli, tmp_path):
    with pytest.raises(UsageError) as error:
        _package(run_cli, tmp_path, core_row={**CORE_ROW, "not_a_real_term": "x"})
    assert str(error.value) == (
        "build refuses non-Darwin-Core column(s): 'not_a_real_term' is not a term in "
        "dwc_terms.json"
    )


def test_package_reports_a_missing_metadata_field_as_a_usage_error(run_cli, tmp_path):
    with pytest.raises(UsageError) as error:
        _package(run_cli, tmp_path, metadata={"title": "Test dataset"})
    assert str(error.value) == "manifest is missing required field 'creators' for eml.xml"


def test_package_reports_the_dynamic_properties_keys_it_moved_to_emof(run_cli, tmp_path):
    properties = json.dumps({"temp_C": "12.5", "notes": "clear day"})
    result = _package(
        run_cli, tmp_path, core_row={**CORE_ROW, "dynamicProperties": properties}, extra=["--json"]
    )
    assert json.loads(result.render())["outputs"]["measurements"] == ["temp_C"]
    assert result.text.endswith(". Moved to eMoF: temp_C")
