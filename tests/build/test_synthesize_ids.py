from __future__ import annotations

from dataclasses import dataclass

import pytest

from edna2dwc.build.join_taxonomy import join_taxonomy
from edna2dwc.build.synthesize_ids import check_sequence_columns, synthesize_ids
from edna2dwc.common.findings import FindingsLog
from edna2dwc.conversion.answers import DatasetIdError
from tests.tables import dicts, table_of


@dataclass
class _Ids:
    rows: list[dict[str, str]]
    findings: FindingsLog


def _step(result) -> _Ids:
    return _Ids(dicts(result.table), result.findings)


def _ids(rows, **options) -> _Ids:
    return _step(synthesize_ids(table_of(rows), **options))


def test_synthesize_ids_never_overwrites_an_existing_material_sample_id():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "1", "materialSampleID": "custom"}]
    result = _ids(rows, dataset_id="ds1")
    assert result.rows[0]["materialSampleID"] == "custom"


def test_synthesized_rows_carry_no_consumed_column():
    result = _ids([{"sampleID": "S1", "featureID": "f1", "count": "1"}], dataset_id="ds1")

    (row,) = result.rows
    assert row["occurrenceID"] == "ds1:S1:f1"
    assert row["materialSampleID"] == "S1"
    assert {"sampleID", "featureID", "count"}.isdisjoint(row)


def test_synthesize_ids_refuses_a_blank_dataset_id_rather_than_keying_every_row_on_nothing():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "1"}]
    with pytest.raises(DatasetIdError, match="blank"):
        _ids(rows, dataset_id="")


REFERENCE_SEQUENCE = (
    "GTTAAGTTCAATACAAAGTCATTCAGGAGCAGCAGTTGACTTAGCAATTTTTAGTTTACATTTAGCGGGAGCATCTTCGAT"
    "ATTAGGAGCAGTTAATTTCATAACAACAATTTTAAATATGCGTAACCCAGGTCAAAGTTTATATCGTATGCCGTCTTCTGC"
    "TTGGACAATTCATGTTACAGCATTCTTATTACTTTTA"
)
REFERENCE_TAXON_ID = "ASV:4d4074142823052b590c11a46c0bddd5"


def _resolved(lineage_key: str, **overrides: str) -> dict[str, str]:
    row = {
        "lineage_key": lineage_key,
        "scientificName": "Aaptos",
        "scientificNameID": "urn:lsid:marinespecies.org:taxname:132064",
        "taxonRank": "Genus",
        "scientificNameAuthorship": "",
        "taxonomicStatus": "accepted",
        "aphia_id": "132064",
        "taxonConceptID": "",
        "kingdom": "Animalia",
        "phylum": "",
        "class": "",
        "order": "",
        "family": "",
        "genus": "Aaptos",
        "resolution_path": "leaf",
        "needs_review": "false",
        "review_reason": "",
        "candidate_ids": "",
        "gbif_usage_key": "",
    }
    return {**row, **overrides}


def _joined_and_synthesized(resolved: dict[str, str], **occurrence: str):
    row = {"sampleID": "S1", "featureID": "f1", "count": "3", "lineage_key": "k", **occurrence}
    joined = join_taxonomy(table_of([row]), {"k": resolved})
    return _step(synthesize_ids(joined, dataset_id="ds1"))


def test_a_worms_row_takes_the_sequence_hash_as_taxon_id():
    result = _joined_and_synthesized(_resolved("k"), DNA_sequence=REFERENCE_SEQUENCE)
    row = result.rows[0]
    assert row["taxonID"] == REFERENCE_TAXON_ID
    assert row["scientificNameID"] == "urn:lsid:marinespecies.org:taxname:132064"
    assert "aphia_id" not in row


def test_a_gbif_only_row_takes_the_sequence_hash_never_a_gbif_key():
    resolved = _resolved(
        "k",
        scientificName="Microtrichaceae",
        scientificNameID="",
        aphia_id="",
        taxonConceptID="https://www.gbif.org/species/4321",
        gbif_usage_key="4321",
    )
    result = _joined_and_synthesized(resolved, DNA_sequence=REFERENCE_SEQUENCE.lower())
    row = result.rows[0]
    assert row["taxonID"] == REFERENCE_TAXON_ID
    assert row["taxonConceptID"] == "https://www.gbif.org/species/4321"
    assert "gbif_usage_key" not in row


def test_a_row_with_no_sequence_leaves_taxon_id_blank_and_says_so():
    result = _joined_and_synthesized(_resolved("k"), featureID="4d4074142823052b590c11a46c0bddd5")
    assert result.rows[0]["taxonID"] == ""
    blank = [f for f in result.findings.findings if f.code == "TAXON_ID_BLANK"]
    assert len(blank) == 1
    assert blank[0].count == 1


def test_the_column_published_as_dna_sequence_is_hashed():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "1", "DNA_sequence": REFERENCE_SEQUENCE}
    ]
    result = _ids(rows, dataset_id="ds1")
    assert result.rows[0]["taxonID"] == REFERENCE_TAXON_ID


def test_a_source_taxon_id_is_kept():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "taxonID": "ASV:supplied",
            "DNA_sequence": REFERENCE_SEQUENCE,
        }
    ]
    result = _ids(rows, dataset_id="ds1")
    assert result.rows[0]["taxonID"] == "ASV:supplied"
    assert not result.findings.findings


def test_a_hash_shaped_feature_id_that_is_not_the_sequence_hash_is_reported():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "0123456789abcdef0123456789abcdef",
            "count": "1",
            "DNA_sequence": REFERENCE_SEQUENCE,
        },
        {
            "sampleID": "S1",
            "featureID": "4d4074142823052b590c11a46c0bddd5",
            "count": "1",
            "DNA_sequence": REFERENCE_SEQUENCE,
        },
        {
            "sampleID": "S2",
            "featureID": "ASV_17",
            "count": "1",
            "DNA_sequence": REFERENCE_SEQUENCE,
        },
    ]
    result = _ids(rows, dataset_id="ds1")
    assert {r["taxonID"] for r in result.rows} == {REFERENCE_TAXON_ID}
    mismatched = [f for f in result.findings.findings if f.code == "FEATURE_ID_NOT_SEQUENCE_HASH"]
    assert len(mismatched) == 1
    assert mismatched[0].count == 1


def _only(result, code: str):
    (finding,) = [f for f in result.findings.findings if f.code == code]
    return finding


def test_a_second_sequence_column_that_disagrees_with_the_published_one_is_reported():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "DNA_sequence": REFERENCE_SEQUENCE,
            "sequence": "ACGT",
        },
        {
            "sampleID": "S1",
            "featureID": "f2",
            "count": "1",
            "DNA_sequence": "ACGT",
            "sequence": "acg-t",
        },
    ]
    (finding,) = check_sequence_columns(table_of(rows), "DNA_sequence").findings
    assert (finding.code, finding.count) == ("SEQUENCE_COLUMNS_DISAGREE", 1)


def test_a_value_that_is_not_a_sequence_gives_no_taxon_id():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "1", "DNA_sequence": "NNNN"}]
    result = _ids(rows, dataset_id="ds1")
    assert result.rows[0]["taxonID"] == ""
    assert _only(result, "TAXON_ID_BLANK").count == 1


def test_sequence_columns_that_agree_are_not_reported():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "DNA_sequence": "ACGT", "sequence": "acg-t"},
    ]
    assert check_sequence_columns(table_of(rows), "DNA_sequence").findings == []
