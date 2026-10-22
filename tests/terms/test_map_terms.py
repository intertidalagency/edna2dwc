from __future__ import annotations

import pytest

    ALIAS_TABLE,
    propose_mapping,
    read_mapping_tsv,
    write_mapping_tsv,
)

TERMS_TABLE = {
    "scientificName": {},
    "DNA_sequence": {},
    "materialSampleID": {},
    "eventID": {},
    "locationID": {},
    "decimalLatitude": {},
    "decimalLongitude": {},
    "_notes": {"ignored": True},
}




    header = ["verbatim_sample_name", "materialSampleID"]
    aliases = dict(ALIAS_TABLE)
    aliases["materialSampleID"] = (*aliases["materialSampleID"], "verbatim_sample_name")


    by_column = {p.source_column: p for p in proposals}
    assert by_column["materialSampleID"].target == "materialSampleID"
    assert by_column["materialSampleID"].basis == "exact"
    assert by_column["verbatim_sample_name"].target == ""
    assert by_column["verbatim_sample_name"].basis == "ambiguous"
    assert any(f.code == "TERM_TARGET_COLLISION" for f in collisions.findings)


def test_target_collision_two_real_columns_fight_over_one_target():
    proposals, collisions = propose_mapping(header, TERMS_TABLE)
    targets = [p.target for p in proposals]
    assert targets.count("decimalLatitude") == 1
    assert any(f.code == "TERM_TARGET_COLLISION" for f in collisions.findings)


def test_mapping_tsv_round_trips():
    proposals, _ = propose_mapping(["scientificName", "sample_id"], TERMS_TABLE)
    text = write_mapping_tsv(proposals)
    round_tripped = read_mapping_tsv(text)




    proposals, _ = propose_mapping(["scientificName", "sample_id"], TERMS_TABLE)
    round_tripped = read_mapping_tsv(text)
    assert len(round_tripped) == 2


def test_read_mapping_tsv_raises_a_clear_error_on_a_malformed_row():
    text = "source_column\ttarget\tbasis\nscientificName\tscientificName\n"
    with pytest.raises(ValueError, match="line 2"):
        read_mapping_tsv(text)


def test_mapping_tsv_sanitizes_embedded_tabs_and_newlines_in_a_column_name():
    proposals, _ = propose_mapping(["weird\tcolumn\nname"], TERMS_TABLE)
    text = write_mapping_tsv(proposals)
    round_tripped = read_mapping_tsv(text)
    assert round_tripped[0].source_column == "weird column name"
