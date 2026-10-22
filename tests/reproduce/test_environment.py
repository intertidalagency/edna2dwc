from __future__ import annotations

import yaml



def test_capture_current_environment_reads_real_installed_versions():
    assert record.python
    assert record.pyproj_version
    assert record.proj_data_version
    assert all(record.dependencies.values())


def test_environment_record_round_trips_through_to_dict_and_from_dict():
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={"openpyxl": "3.1.2"},
    )


        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={"openpyxl": "3.1.2", "h5py": "3.11.0"},
    )


def test_record_environment_writes_the_block(tmp_path):
    config_path = tmp_path / "conversion.yaml"
    config_path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={"openpyxl": "3.1.2"},
    )


    raw = yaml.safe_load(config_path.read_text())
    assert raw["dataset_id"] == "ds1"
    assert raw["environment"]["pyproj"] == {"version": "3.6.1", "proj_data": "9.4.0"}


    config_path = tmp_path / "conversion.yaml"
    config_path.write_text(
    )
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={},
    )


    raw = yaml.safe_load(config_path.read_text())


    config_path = tmp_path / "conversion.yaml"
    config_path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")


def test_load_environment_reads_back_what_was_recorded(tmp_path):
    config_path = tmp_path / "conversion.yaml"
    config_path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")
        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={"openpyxl": "3.1.2"},
    )

