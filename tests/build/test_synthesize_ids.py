from __future__ import annotations

import pytest



def test_synthesize_ids_never_overwrites_an_existing_material_sample_id():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "1", "materialSampleID": "custom"}]
    assert result.rows[0]["materialSampleID"] == "custom"




def test_synthesize_ids_refuses_a_blank_dataset_id_rather_than_keying_every_row_on_nothing():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "1"}]
    with pytest.raises(DatasetIdError, match="blank"):
