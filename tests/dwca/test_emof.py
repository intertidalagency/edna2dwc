import json

import pytest





@pytest.mark.parametrize(
    [
    ],
)
):




    rows = [
        {
            "occurrenceID": "occ1",
            "dynamicProperties": json.dumps({"temp_C": "12.5", "notes": "clear day"}),
        },
        {
            "occurrenceID": "occ2",
            "dynamicProperties": json.dumps({"temp_C": "13.0", "notes": "cloudy"}),
        },
    ]




def test_select_and_build_emof_handles_rows_with_no_dynamic_properties_at_all():
    rows = [{"occurrenceID": "occ1", "scientificName": "Mytilus californianus"}]
    assert result.emof_rows == []
    assert "dynamicProperties" not in result.core_rows[0]
