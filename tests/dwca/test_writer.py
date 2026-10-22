import json
from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile

import pytest



TERM_TABLE = {
    "measurementTypeID": {"uri": "http://rs.iobis.org/obis/terms/measurementTypeID"},
    "measurementUnitID": {"uri": "http://rs.iobis.org/obis/terms/measurementUnitID"},
    "measurementValueID": {"uri": "http://rs.iobis.org/obis/terms/measurementValueID"},
}





    out_dir = tmp_path / "archive"
        dataset_id="urn:uuid:test-dataset",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
    )
    return out_dir




    ]






def test_write_archive_zip_is_deflated_not_stored(tmp_path):


def test_write_archive_promotes_a_measurement_to_emof_by_default(tmp_path):
    emof_rows = list(read_rows(out_dir / "extendedmeasurementorfact.txt", delimiter="\t"))
    assert emof_rows[0]["measurementType"] == "temperature"
    core_rows = list(read_rows(out_dir / "occurrence.txt", delimiter="\t"))


        extensions={},
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
    )


@pytest.mark.parametrize(
    "tz", ["UTC", "America/Los_Angeles", "Asia/Kolkata", "Pacific/Kiritimati"]
)
def test_write_archive_zip_timestamp_is_independent_of_local_timezone(tmp_path, tz, monkeypatch):
    monkeypatch.setenv("TZ", tz)
    try:
    finally:
        monkeypatch.delenv("TZ", raising=False)


def test_check_no_duplicate_row_types_rejects_an_unrecognized_key():
