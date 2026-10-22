from __future__ import annotations

import pytest



def test_synthesize_ids_never_overwrites_an_existing_material_sample_id():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "1", "materialSampleID": "custom"}]
    assert result.rows[0]["materialSampleID"] == "custom"


