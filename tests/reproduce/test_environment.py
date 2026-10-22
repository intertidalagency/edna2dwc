from __future__ import annotations

import yaml

from edna2dwc.reproduce import environment


def test_capture_current_environment_reads_real_installed_versions():
    record = environment.capture_current_environment()
    assert record.python
    assert record.pyproj_version
    assert record.proj_data_version
    assert set(record.dependencies) == set(environment.READER_PACKAGES)
    assert all(record.dependencies.values())


def test_environment_record_round_trips_through_to_dict_and_from_dict():
    record = environment.EnvironmentRecord(
        edna2dwc_version="1.0.3",
        edna2dwc_commit="abc123",
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={"openpyxl": "3.1.2"},
    )
    assert environment.EnvironmentRecord.from_dict(record.to_dict()) == record


def test_every_pin_but_edna2dwc_itself_can_be_reconstructed():
    record = environment.EnvironmentRecord(
        edna2dwc_version="1.0.3",
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={"openpyxl": "3.1.2", "h5py": "3.11.0"},
    )
    assert record.all_pins() == {"edna2dwc": "1.0.3", "openpyxl": "3.1.2", "h5py": "3.11.0"}
    assert record.reconstructable_pins() == {"openpyxl": "3.1.2", "h5py": "3.11.0"}


def test_record_environment_writes_the_block(tmp_path):
    config_path = tmp_path / "conversion.yaml"
    config_path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")
    record = environment.EnvironmentRecord(
        edna2dwc_version="1.0.3",
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={"openpyxl": "3.1.2"},
    )

    environment.record_environment(config_path, record)

    raw = yaml.safe_load(config_path.read_text())
    assert raw["dataset_id"] == "ds1"
    assert raw["environment"]["edna2dwc_version"] == "1.0.3"
    assert raw["environment"]["pyproj"] == {"version": "3.6.1", "proj_data": "9.4.0"}


def test_record_environment_replaces_the_block_an_earlier_build_wrote(tmp_path):
    config_path = tmp_path / "conversion.yaml"
    config_path.write_text(
        yaml.safe_dump({"environment": {"edna2dwc_version": "0.9.0"}}), encoding="utf-8"
    )
    record = environment.EnvironmentRecord(
        edna2dwc_version="1.0.3",
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={},
    )

    environment.record_environment(config_path, record)

    raw = yaml.safe_load(config_path.read_text())
    assert raw["environment"]["edna2dwc_version"] == "1.0.3"


def test_record_environment_creates_a_missing_conversion_yaml(tmp_path):
    config_path = tmp_path / "conversion.yaml"
    record = environment.EnvironmentRecord(
        edna2dwc_version="1.0.3",
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={},
    )

    environment.record_environment(config_path, record)

    assert environment.load_environment(config_path) == record


def test_load_environment_returns_none_without_a_file_or_an_environment_block(tmp_path):
    config_path = tmp_path / "conversion.yaml"
    assert environment.load_environment(config_path) is None
    config_path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")
    assert environment.load_environment(config_path) is None


def test_load_environment_reads_back_what_was_recorded(tmp_path):
    config_path = tmp_path / "conversion.yaml"
    config_path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")
    record = environment.EnvironmentRecord(
        edna2dwc_version="1.0.3",
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={"openpyxl": "3.1.2"},
    )
    environment.record_environment(config_path, record)

    assert environment.load_environment(config_path) == record


def test_a_record_written_before_commits_were_recorded_loads_with_none():
    raw = environment.EnvironmentRecord(
        edna2dwc_version="1.0.3", python="3.12.4", pyproj_version="", proj_data_version=""
    ).to_dict()
    raw.pop("edna2dwc_commit")
    assert environment.EnvironmentRecord.from_dict(raw).edna2dwc_commit == ""


def test_the_version_table_compares_the_commit_too():
    def record(commit: str) -> environment.EnvironmentRecord:
        return environment.EnvironmentRecord(
            edna2dwc_version="1.0.3",
            edna2dwc_commit=commit,
            python="3.12.4",
            pyproj_version="",
            proj_data_version="",
        )

    rows = environment.version_diff_table(record("abc"), record("def"))
    (commit_row,) = [row for row in rows if row["package"] == "edna2dwc commit"]
    assert commit_row == {
        "package": "edna2dwc commit",
        "recorded": "abc",
        "current": "def",
        "changed": True,
    }
