from __future__ import annotations

import pytest


RESOLVED = {
    "k1": {
        "lineage_key": "k1",
        "scientificName": "Aaptos",
        "scientificNameID": "urn:lsid:marinespecies.org:taxname:132064",
        "taxonRank": "Genus",
        "scientificNameAuthorship": "",
        "taxonomicStatus": "accepted",
        "taxonConceptID": "",
        "kingdom": "Animalia",
        "phylum": "Porifera",
        "class": "",
        "order": "",
        "family": "",
        "genus": "Aaptos",
        "needs_review": "false",
        "review_reason": "",
        "candidate_ids": "",
    }
}




    occurrence_rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "10", "lineage_key": "missing_key"}
    ]
    with pytest.raises(JoinAuditError, match="missing_key"):


def test_needs_review_reaches_identification_remarks():
    resolved = {
        **RESOLVED,
        "k2": {
            **RESOLVED["k1"],
            "lineage_key": "k2",
            "needs_review": "true",
            "review_reason": "ambiguous_homonym",
            "candidate_ids": "1|2",
        },
    }
    occurrence_rows = [{"sampleID": "S1", "featureID": "f2", "count": "5", "lineage_key": "k2"}]


def test_no_review_reason_means_no_identification_remarks_column():
    occurrence_rows = [{"sampleID": "S1", "featureID": "f1", "count": "10", "lineage_key": "k1"}]


def test_preexisting_identification_remarks_is_preserved_not_overwritten():
    occurrence_rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "10",
            "lineage_key": "k1",
            "identificationRemarks": "identified by J. Smith",
        }
    ]


def test_preexisting_identification_remarks_is_appended_to_when_flagged_for_review():
    resolved = {
        **RESOLVED,
        "k2": {
            **RESOLVED["k1"],
            "lineage_key": "k2",
            "needs_review": "true",
            "review_reason": "ambiguous_homonym",
            "candidate_ids": "1|2",
        },
    }
    occurrence_rows = [
        {
            "sampleID": "S1",
            "featureID": "f2",
            "count": "5",
            "lineage_key": "k2",
            "identificationRemarks": "identified by J. Smith",
        }
    ]


