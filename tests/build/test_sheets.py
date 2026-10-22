import pytest

from edna2dwc.build import sheets
from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import connect


def test_the_mapping_reason_names_each_column_that_becomes_measurement_rows():
    reason = sheets.mapping_reason(FindingsLog(), 3, ["depth_nominal", "salinity_psu"])
    assert "1 column(s) staying in dynamicProperties" in reason
    assert "depth_nominal, salinity_psu will move to extendedmeasurementorfact" in reason


def test_a_confirmed_sheet_refuses_a_machine_reply_whatever_whitespace_surrounds_it(tmp_path):
    (tmp_path / "confirmed").mkdir()
    (tmp_path / sheets.DERIVED_VALUES.confirmed).write_text(
        'sampleID\tfeatureID\tconfirmed\nS1\tf1\tPI: yes\nS2\tf1\t"Agent.\n"\n', newline="\n"
    )

    with connect() as con, pytest.raises(sheets.SheetRefused, match="S2: confirmed: 'Agent"):
        sheets.confirmed_table(tmp_path, sheets.DERIVED_VALUES, con)
