from __future__ import annotations

import math
import re

import httpx
import pytest

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.tsv import read_tab_separated_rows
from edna2dwc.conversion.answers import TaxonomySettings
from edna2dwc.taxonomy import api_usage, resolve_taxonomy
from edna2dwc.taxonomy.gbif import GbifClient
from edna2dwc.taxonomy.register_http import TIMEOUT
from edna2dwc.taxonomy.resolve_taxonomy import (
    RANKS_FROM_GENUS_UP,
    ResolvedTaxon,
    TaxonResolver,
    lock_findings,
    mass_collapsed_keys,
    register_clients,
    step,
)
from edna2dwc.taxonomy.worms import BATCH_SIZE, WormsClient
from tests.taxonomy.conversion_dir import registers_answering


@pytest.fixture(autouse=True)
def _reset_api_usage():
    api_usage.reset()
    yield
    api_usage.reset()


def _record(**overrides) -> dict:
    base = {
        "AphiaID": 1,
        "url": "https://www.marinespecies.org/aphia.php?p=taxdetails&id=1",
        "scientificname": "Placeholder",
        "authority": "",
        "taxonRankID": 220,
        "rank": "Species",
        "status": "accepted",
        "unacceptreason": None,
        "valid_AphiaID": None,
        "valid_name": None,
        "valid_authority": None,
        "parentNameUsageID": 0,
        "kingdom": "",
        "phylum": "",
        "class": "",
        "order": "",
        "family": "",
        "genus": "",
        "citation": "Placeholder citation, accessed through WoRMS",
        "lsid": "urn:lsid:marinespecies.org:taxname:1",
        "isMarine": 1,
        "isBrackish": 0,
        "isFreshwater": 0,
        "isTerrestrial": 0,
        "isExtinct": 0,
        "match_type": "exact",
        "modified": "2020-05-14T15:18:26.397Z",
    }
    base.update(overrides)
    return base


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _worms_transport(name_to_records, sent: list[str] | None = None):
    def handler(request):
        names = request.url.params.get_list("scientificnames[]")
        if sent is not None:
            sent.extend(names)
        return httpx.Response(200, json=[name_to_records.get(n, []) for n in names])

    return handler


def _resolver(
    name_to_records: dict[str, list[dict]],
    *,
    sent: list[str] | None = None,
    require_confident: bool = False,
) -> TaxonResolver:
    worms = WormsClient(client=_client(_worms_transport(name_to_records, sent)))
    return TaxonResolver(worms, require_confident=require_confident)


def _log(*results: ResolvedTaxon) -> FindingsLog:
    return lock_findings(result.to_row() for result in results)


def _codes(result: ResolvedTaxon) -> list[str]:
    return [f.code for f in _log(result).findings]


AAPTOS = _record(AphiaID=132064, scientificname="Aaptos", kingdom="Animalia", genus="Aaptos")
PRASINODERMA_COLONIALE = _record(
    AphiaID=375881,
    scientificname="Prasinoderma coloniale",
    kingdom="Plantae",
    genus="Prasinoderma",
)
CYANOBACTERIA = _record(
    AphiaID=2, scientificname="Cyanobacteria", kingdom="Bacteria", phylum="Cyanobacteria"
)
CHLOROPLAST_RECORDS = {
    "Prasinoderma coloniale": [PRASINODERMA_COLONIALE],
    "Cyanobacteria": [CYANOBACTERIA],
}
ACTINOCYCLUS_DIATOM = _record(
    AphiaID=1, scientificname="Actinocyclus", kingdom="Chromista", phylum="Bacillariophyta"
)
ACTINOCYCLUS_ANIMAL_DIATOM = _record(
    AphiaID=2, scientificname="Actinocyclus", kingdom="Animalia", phylum="Bacillariophyta"
)
ACTINOCYCLUS_MOLLUSC = _record(
    AphiaID=2, scientificname="Actinocyclus", kingdom="Animalia", phylum="Mollusca"
)
UNBREAKABLE_ACTINOCYCLUS = {"Actinocyclus": [ACTINOCYCLUS_DIATOM, ACTINOCYCLUS_ANIMAL_DIATOM]}
BREAKABLE_ACTINOCYCLUS = {"Actinocyclus": [ACTINOCYCLUS_DIATOM, ACTINOCYCLUS_MOLLUSC]}
HOMONYMUS_BACILLARIOPHYCEAE = _record(
    AphiaID=1,
    scientificname="Homonymus",
    kingdom="Chromista",
    phylum="Bacillariophyta",
    **{"class": "Bacillariophyceae"},
)
HOMONYMUS_COSCINODISCOPHYCEAE = _record(
    AphiaID=2,
    scientificname="Homonymus",
    kingdom="Chromista",
    phylum="Bacillariophyta",
    **{"class": "Coscinodiscophyceae"},
)
LEUCORAJA_RECORDS = {
    "Leucoraja ocellata": [
        _record(
            AphiaID=10, scientificname="Leucoraja ocellata", kingdom="Animalia", genus="Leucoraja"
        )
    ],
    "Leucoraja erinacea": [
        _record(
            AphiaID=11, scientificname="Leucoraja erinacea", kingdom="Animalia", genus="Leucoraja"
        )
    ],
    "Leucoraja": [
        _record(AphiaID=12, scientificname="Leucoraja", kingdom="Animalia", genus="Leucoraja")
    ],
}


def test_leaf_exact_match():
    result = _resolver({"Aaptos": [AAPTOS]}).resolve("Aaptos", {"kingdom": "Animalia"})
    assert result.resolution_path == "leaf"
    assert result.scientific_name_id == "urn:lsid:marinespecies.org:taxname:132064"
    assert result.needs_review is False


def test_chloroplast_kingdom_reject_backs_off():
    result = _resolver(CHLOROPLAST_RECORDS).resolve(
        "Prasinoderma coloniale",
        {"kingdom": "Bacteria", "phylum": "Cyanobacteria", "genus": "Chloroplast"},
    )
    assert result.kingdom != "Plantae"
    assert result.resolution_path == "rank_backoff"
    assert result.scientific_name == "Cyanobacteria"
    assert _codes(result) == ["TAXON_REJECTED_ORGANELLE"]
    assert _log(result).findings[0].count == 1


@pytest.mark.parametrize(
    "terminal_name",
    [
        "Unassigned",
        "incertae sedis",
        "uncultured bacterium",
        "sp.",
        "cf.",
        "  ",
        "(Author, 2020)",
        "",
    ],
)
def test_a_no_assignment_or_empty_terminal_never_reaches_worms(terminal_name):
    sent: list[str] = []
    result = _resolver({}, sent=sent).resolve(terminal_name, {})
    assert sent == []
    assert result.resolution_path == "incertae_sedis_placeholder"
    assert result.scientific_name_id == "urn:lsid:marinespecies.org:taxname:12"
    assert result.kingdom == "Biota incertae sedis"


def test_uninformative_kingdom_rejects_non_confident_match():
    resolver = _resolver(
        {
            "Pelargonium": [
                _record(
                    AphiaID=249154,
                    scientificname="Pelargonium",
                    kingdom="Animalia",
                    phylum="Arthropoda",
                    match_type="fuzzy",
                    status="accepted",
                )
            ]
        }
    )
    result = resolver.resolve("Pelargonium", {"kingdom": "Eukaryota"})
    assert result.resolution_path == "biota_fallback"
    assert result.scientific_name != "Pelargonium"


@pytest.mark.parametrize(
    "source_ranks",
    [{"kingdom": "Eukaryota"}, {"kingdom": "Unknownia", "phylum": "Bacillariophyta"}],
)
def test_an_unbreakable_homonym_tie_never_guesses_and_is_labeled_leaf(source_ranks):
    result = _resolver(UNBREAKABLE_ACTINOCYCLUS).resolve("Actinocyclus", source_ranks)
    assert result.needs_review is True
    assert result.review_reason == "ambiguous_homonym"
    assert set(result.candidate_ids.split("|")) == {"1", "2"}
    assert result.resolution_path == "leaf"
    assert "TAXON_AMBIGUOUS_HOMONYM" in _codes(result)


def test_homonym_disambiguated_by_source_phylum():
    result = _resolver(BREAKABLE_ACTINOCYCLUS).resolve(
        "Actinocyclus", {"kingdom": "Chromista", "phylum": "Bacillariophyta"}
    )
    assert result.resolution_path == "homonym_disambiguated"
    assert result.aphia_id == "1"
    assert result.needs_review is False
    assert _codes(result) == ["TAXON_HOMONYM_DISAMBIGUATED"]


def test_source_phylum_matching_neither_candidate_is_a_distinct_mismatch():
    result = _resolver(BREAKABLE_ACTINOCYCLUS).resolve(
        "Actinocyclus", {"kingdom": "Unknownia", "phylum": "Nope"}
    )
    assert result.needs_review is True
    assert result.review_reason == "homonym_source_mismatch"
    assert set(result.candidate_ids.split("|")) == {"1", "2"}


def test_ambiguous_homonym_reached_via_real_backoff_is_labeled_rank_backoff():
    result = _resolver(UNBREAKABLE_ACTINOCYCLUS).resolve(
        "Some unresolvable terminal name",
        {"kingdom": "Unknownia", "phylum": "Bacillariophyta", "genus": "Actinocyclus"},
    )
    assert result.needs_review is True
    assert result.review_reason == "ambiguous_homonym"
    assert result.resolution_path == "rank_backoff"


HOMONYMUS_BY_CLASS = {"Homonymus": [HOMONYMUS_BACILLARIOPHYCEAE, HOMONYMUS_COSCINODISCOPHYCEAE]}


def test_combined_phylum_and_class_narrows_a_phylum_only_tie():
    result = _resolver(HOMONYMUS_BY_CLASS).resolve(
        "Homonymus",
        {"kingdom": "Chromista", "phylum": "Bacillariophyta", "class": "Coscinodiscophyceae"},
    )
    assert result.resolution_path == "homonym_disambiguated"
    assert result.aphia_id == "2"
    assert result.needs_review is False


def test_combined_signal_still_ambiguous_falls_back_cleanly():
    result = _resolver(HOMONYMUS_BY_CLASS).resolve(
        "Homonymus", {"kingdom": "Chromista", "phylum": "Bacillariophyta", "class": "Nope"}
    )
    assert result.needs_review is True
    assert result.review_reason == "ambiguous_homonym"


def test_homonym_source_mismatch_when_both_signals_conflict():
    gastropod = _record(
        AphiaID=2,
        scientificname="Homonymus",
        kingdom="Animalia",
        phylum="Mollusca",
        **{"class": "Gastropoda"},
    )
    result = _resolver({"Homonymus": [HOMONYMUS_BACILLARIOPHYCEAE, gastropod]}).resolve(
        "Homonymus", {"kingdom": "Unknownia", "phylum": "Nope", "class": "AlsoNope"}
    )
    assert result.needs_review is True
    assert result.review_reason == "homonym_source_mismatch"


def test_homonym_tiebreak_does_not_compare_phylum_against_a_class_value():
    resolver = _resolver(
        {
            "Homonymus": [
                _record(
                    AphiaID=1,
                    scientificname="Homonymus",
                    kingdom="Chromista",
                    phylum="Insecta",
                    **{"class": "Bacillariophyceae"},
                ),
                _record(
                    AphiaID=2,
                    scientificname="Homonymus",
                    kingdom="Animalia",
                    phylum="Arthropoda",
                    **{"class": "Insecta"},
                ),
            ]
        }
    )
    result = resolver.resolve("Homonymus", {"kingdom": "Animalia", "class": "Insecta"})
    assert result.resolution_path == "homonym_disambiguated"
    assert result.aphia_id == "2"


def test_homonym_tiebreak_with_no_phylum_and_no_class_never_guesses():
    resolver = _resolver(
        {
            "Homonymus": [
                _record(AphiaID=1, scientificname="Homonymus", kingdom="Chromista"),
                _record(AphiaID=2, scientificname="Homonymus", kingdom="Animalia"),
            ]
        }
    )
    result = resolver.resolve("Homonymus", {"kingdom": "Unknownia"})
    assert result.review_reason == "ambiguous_homonym"
    assert result.needs_review is True
    assert set(result.candidate_ids.split("|")) == {"1", "2"}


def test_exact_but_unaccepted_match_is_flagged_by_status_not_match_type():
    resolver = _resolver(
        {
            "Homonymus unacceptus": [
                _record(
                    AphiaID=7,
                    scientificname="Homonymus unacceptus",
                    kingdom="Animalia",
                    status="unaccepted",
                    match_type="exact",
                )
            ]
        }
    )
    result = resolver.resolve("Homonymus unacceptus", {"kingdom": "Animalia"})
    assert result.needs_review is True
    assert result.review_reason == "unaccepted_status:unaccepted"

    assert _log(result).findings == []


def test_rank_backoff_tries_genus_before_family():
    resolver = _resolver(
        {
            "Nonexistentus": [],
            "Suberitidae": [
                _record(
                    AphiaID=5,
                    scientificname="Suberitidae",
                    kingdom="Animalia",
                    family="Suberitidae",
                )
            ],
        }
    )
    result = resolver.resolve("Nonexistentus", {"kingdom": "Animalia", "family": "Suberitidae"})
    assert result.resolution_path == "rank_backoff"
    assert result.scientific_name == "Suberitidae"


def test_rank_backoff_landing_on_a_tied_family_still_disambiguates_by_phylum():
    resolver = _resolver(
        {
            "Nonexistentus": [],
            "Suberitidae": [
                _record(
                    AphiaID=20,
                    scientificname="Suberitidae",
                    kingdom="Animalia",
                    family="Suberitidae",
                    phylum="Porifera",
                ),
                _record(
                    AphiaID=21,
                    scientificname="Suberitidae",
                    kingdom="Animalia",
                    family="Suberitidae",
                    phylum="Cnidaria",
                ),
            ],
        }
    )
    result = resolver.resolve(
        "Nonexistentus", {"kingdom": "Animalia", "family": "Suberitidae", "phylum": "Porifera"}
    )
    assert result.resolution_path == "homonym_disambiguated"
    assert result.aphia_id == "20"
    assert result.needs_review is False


@pytest.mark.parametrize("kingdom", ["Animalia", "Eukaryota"])
def test_a_compound_name_backs_off_to_its_shared_genus(kingdom):
    result = _resolver(LEUCORAJA_RECORDS).resolve(
        "Leucoraja ocellata or erinacea", {"kingdom": kingdom}
    )
    assert result.resolution_path == "compound_common_ancestor"
    assert result.genus == "Leucoraja"


def test_terminal_fallback_when_nothing_resolves():
    result = _resolver({}).resolve("Totally madeupii", {})
    assert result.resolution_path == "biota_fallback"
    assert result.scientific_name_id == "urn:lsid:marinespecies.org:taxname:12"
    (finding,) = _log(result).findings
    assert (finding.code, finding.count) == ("TAXON_UNRESOLVED", 1)
    assert "at any rank" not in finding.message
    assert "placeholder taxon" in finding.message


def test_terminal_fallback_biota_option_produces_a_blank_kingdom():
    worms = WormsClient(client=_client(_worms_transport({})))
    result = TaxonResolver(worms, terminal_fallback="biota").resolve("Totally madeupii", {})
    assert result.resolution_path == "biota_fallback"
    assert result.aphia_id == "1"
    assert result.kingdom == ""


def test_compound_part_with_its_own_homonym_tie_still_finds_a_shared_ancestor():
    erinacea = LEUCORAJA_RECORDS["Leucoraja erinacea"][0]
    tied = {**LEUCORAJA_RECORDS, "Leucoraja erinacea": [erinacea, {**erinacea, "AphiaID": 13}]}
    result = _resolver(tied).resolve("Leucoraja ocellata or erinacea", {"kingdom": "Animalia"})
    assert result.resolution_path == "compound_common_ancestor"
    assert result.genus == "Leucoraja"
    assert result.review_reason == (
        "compound_name_common_ancestor; Leucoraja erinacea:ambiguous_homonym:11|13"
    )


GADUS_MORHUA = _record(
    AphiaID=126436,
    scientificname="Gadus morhua",
    kingdom="Animalia",
    family="Gadidae",
    genus="Gadus",
)
GADIDAE = _record(
    AphiaID=125469, scientificname="Gadidae", rank="Family", kingdom="Animalia", family="Gadidae"
)
GADUS = _record(
    AphiaID=125732,
    scientificname="Gadus",
    rank="Genus",
    kingdom="Animalia",
    family="Gadidae",
    genus="Gadus",
)


@pytest.mark.parametrize("name", ["Gadidae / Gadus morhua", "Gadus morhua / Gadidae"])
def test_a_compound_part_without_a_genus_disagrees_at_genus(name):
    resolver = _resolver({"Gadus morhua": [GADUS_MORHUA], "Gadidae": [GADIDAE], "Gadus": [GADUS]})

    result = resolver.resolve(name, {"kingdom": "Animalia"})

    assert result.resolution_path == "compound_common_ancestor"
    assert result.scientific_name == "Gadidae"


def test_a_compound_with_an_unresolved_part_publishes_no_shared_ancestor():
    resolver = _resolver({"Gadus morhua": [GADUS_MORHUA], "Gadus": [GADUS]})

    result = resolver.resolve("Gadus morhua or Xyzzy plugh", {"kingdom": "Animalia"})

    assert result.resolution_path == "compound_common_ancestor"
    assert result.scientific_name == "Biota incertae sedis"
    assert result.review_reason == "compound_name_part_unresolved:Xyzzy plugh"


def _gbif_match(**overrides) -> dict:
    base = {
        "usageKey": 100,
        "scientificName": "Placeholder Author, 1900",
        "canonicalName": "Placeholder",
        "rank": "GENUS",
        "status": "ACCEPTED",
        "confidence": 95,
        "matchType": "EXACT",
        "kingdom": "",
        "phylum": "",
        "class": "",
        "order": "",
        "family": "",
        "genus": "",
        "kingdomKey": 1,
        "phylumKey": 2,
        "classKey": 3,
        "orderKey": 4,
        "familyKey": 5,
        "genusKey": 6,
        "synonym": False,
        "alternatives": [],
    }
    base.update(overrides)
    return base


def _refuse_worms(request):
    raise AssertionError(f"WoRMS was asked: {request.url}")


def _gbif_answering(**match):
    return lambda request: httpx.Response(200, json=_gbif_match(**match))


def _gbif_resolver(
    gbif_handler, worms_handler=None, *, require_confident: bool = False, **settings
) -> TaxonResolver:
    return TaxonResolver(
        WormsClient(client=_client(worms_handler or _worms_transport({}))),
        gbif=GbifClient(client=_client(gbif_handler)),
        require_confident=require_confident,
        **settings,
    )


def _gbif_homonyms(first: dict, second: dict):
    match = _gbif_match(usageKey=1, canonicalName="Homonymus", **first)
    match["alternatives"] = [_gbif_match(usageKey=2, canonicalName="Homonymus", **second)]
    return lambda request: httpx.Response(200, json=match)


DIATOM = {"kingdom": "Chromista", "phylum": "Bacillariophyta"}
MOLLUSC = {"kingdom": "Animalia", "phylum": "Mollusca"}
CORALLINA_RECORDS = {
    "Corallina": [
        _record(AphiaID=1, scientificname="Corallina", kingdom="Plantae", phylum="Chlorophyta"),
        _record(AphiaID=2, scientificname="Corallina", kingdom="Plantae", phylum="Rhodophyta"),
    ]
}


def test_gbif_alone_never_asks_worms():
    resolver = _gbif_resolver(
        _gbif_answering(usageKey=4321, canonicalName="Aaptos", kingdom="Animalia"),
        _refuse_worms,
        registers=("gbif",),
    )
    resolver.prefetch([{"lineage_key": "k", "terminal_name": "Aaptos"}])
    result = resolver.resolve("Aaptos", {}, source_taxon_id="132064")
    assert (result.authority, result.resolution_path) == ("gbif", "leaf")
    assert result.scientific_name_id == "https://www.gbif.org/species/4321"


def test_registers_are_asked_in_the_order_given():
    resolver = _gbif_resolver(
        _gbif_answering(usageKey=4321, canonicalName="Aaptos"),
        _worms_transport({"Aaptos": [AAPTOS]}),
        registers=("gbif", "worms"),
    )
    result = resolver.resolve("Aaptos", {})
    assert (result.authority, result.resolution_path) == ("gbif", "leaf")


def test_a_name_the_first_register_lacks_falls_back_to_the_next():
    resolver = _gbif_resolver(
        _gbif_answering(matchType="NONE"),
        _worms_transport({"Aaptos": [AAPTOS]}),
        registers=("gbif", "worms"),
    )
    result = resolver.resolve("Aaptos", {})
    assert (result.authority, result.resolution_path) == ("worms", "worms_fallback")


def test_gbif_fallback_wins_at_genus_before_worms_tries_family():
    resolver = _gbif_resolver(_gbif_answering(kingdom="Animalia", genus="Suberitidae"))
    result = resolver.resolve(
        "Nonexistentus madeupii",
        {"kingdom": "Animalia", "genus": "Suberitidae", "family": "Suberitidae"},
    )
    assert result.resolution_path == "gbif_fallback"
    assert result.authority == "gbif"


def test_a_gbif_only_name_is_identified_by_its_gbif_species_url():
    resolver = _gbif_resolver(
        _gbif_answering(usageKey=4321, canonicalName="Microtrichaceae", rank="FAMILY")
    )
    result = resolver.resolve("Microtrichaceae", {})
    assert result.authority == "gbif"
    assert result.scientific_name_id == "https://www.gbif.org/species/4321"
    assert result.aphia_id == ""
    assert result.gbif_usage_key == "4321"
    assert result.taxon_concept_id == "https://www.gbif.org/species/4321"
    assert result.to_row()["aphia_id"] == ""
    assert result.to_row()["gbif_usage_key"] == "4321"


def test_gbif_win_still_carries_a_worms_lsid_when_worms_also_resolves():
    resolver = _gbif_resolver(
        _gbif_answering(canonicalName="Aaptos", kingdom="Animalia", genus="Aaptos"),
        _worms_transport({"Aaptos": [AAPTOS]}),
    )
    result = resolver.resolve(
        "Some unrecognized synonym", {"kingdom": "Animalia", "genus": "Aaptidae"}
    )
    assert result.authority == "gbif"
    assert result.scientific_name_id == "urn:lsid:marinespecies.org:taxname:132064"
    assert result.aphia_id == "132064"
    assert result.gbif_usage_key == "100"


def test_gbif_win_follow_up_worms_lookup_rejects_a_wrong_kingdom_homonym():
    resolver = _gbif_resolver(
        _gbif_answering(canonicalName="Actinocyclus", kingdom="Chromista"),
        _worms_transport({"Actinocyclus": [ACTINOCYCLUS_MOLLUSC, ACTINOCYCLUS_DIATOM]}),
    )
    result = resolver.resolve("Some unrecognized synonym", {"kingdom": "Chromista"})
    assert result.authority == "gbif"
    assert result.scientific_name_id == "urn:lsid:marinespecies.org:taxname:1"


def test_gbif_win_follow_up_worms_lookup_uses_the_homonym_tiebreak_without_reporting_it():
    resolver = _gbif_resolver(
        _gbif_answering(canonicalName="Corallina", kingdom="Plantae", phylum="Rhodophyta"),
        _worms_transport(CORALLINA_RECORDS),
    )
    result = resolver.resolve("Some unrecognized synonym", {"kingdom": "Plantae"})
    assert result.authority == "gbif"
    assert result.scientific_name_id == "urn:lsid:marinespecies.org:taxname:2"
    assert not set(_codes(result)) & {"TAXON_HOMONYM_DISAMBIGUATED", "TAXON_AMBIGUOUS_HOMONYM"}


def test_gbif_win_follow_up_worms_lookup_leaves_lsid_blank_on_an_unbreakable_tie():
    resolver = _gbif_resolver(
        _gbif_answering(canonicalName="Corallina", kingdom="Plantae"),
        _worms_transport(CORALLINA_RECORDS),
    )
    result = resolver.resolve("Some unrecognized synonym", {"kingdom": "Plantae"})
    assert result.authority == "gbif"
    assert result.scientific_name_id == "https://www.gbif.org/species/100"


def test_gbif_no_match_falls_through_to_terminal():
    no_match = {"matchType": "NONE", "confidence": 0, "synonym": False}
    resolver = _gbif_resolver(lambda request: httpx.Response(200, json=no_match))
    result = resolver.resolve("Totally madeupii", {})
    assert result.resolution_path == "biota_fallback"


def test_gbif_gets_a_shot_at_the_terminal_name_with_no_rank_structure():
    resolver = _gbif_resolver(
        _gbif_answering(canonicalName="Aaptos", kingdom="Animalia", genus="Aaptos")
    )
    result = resolver.resolve("Aaptos", {})
    assert result.resolution_path == "gbif_fallback"
    assert result.authority == "gbif"


def test_gbif_homonym_disambiguated_by_source_phylum_is_not_flagged_for_review():
    result = _gbif_resolver(_gbif_homonyms(DIATOM, MOLLUSC)).resolve("Homonymus", DIATOM)
    assert result.resolution_path == "homonym_disambiguated"
    assert result.needs_review is False
    assert result.aphia_id == ""
    assert result.gbif_usage_key == "1"
    assert _codes(result) == ["TAXON_HOMONYM_DISAMBIGUATED"]


def test_gbif_ambiguous_homonym_never_guesses():
    result = _gbif_resolver(_gbif_homonyms(DIATOM, DIATOM)).resolve("Homonymus", DIATOM)
    assert result.needs_review is True
    assert result.review_reason == "ambiguous_homonym"
    assert set(result.candidate_ids.split("|")) == {"1", "2"}
    assert _codes(result) == ["TAXON_AMBIGUOUS_HOMONYM"]


def test_gbif_homonym_source_mismatch_when_neither_candidate_agrees():
    result = _gbif_resolver(_gbif_homonyms(DIATOM, MOLLUSC)).resolve(
        "Homonymus", {"kingdom": "Unknownia", "phylum": "Nope"}
    )
    assert result.needs_review is True
    assert result.review_reason == "homonym_source_mismatch"
    assert set(result.candidate_ids.split("|")) == {"1", "2"}


def test_gbif_combined_phylum_and_class_narrows_a_phylum_only_tie():
    resolver = _gbif_resolver(
        _gbif_homonyms(
            {**DIATOM, "class": "Bacillariophyceae"}, {**DIATOM, "class": "Coscinodiscophyceae"}
        )
    )
    result = resolver.resolve("Homonymus", {**DIATOM, "class": "Coscinodiscophyceae"})
    assert result.resolution_path == "homonym_disambiguated"
    assert result.aphia_id == ""
    assert result.gbif_usage_key == "2"
    assert result.needs_review is False


ACCEPTED_SPECIES = {
    "key": 999,
    "scientificName": "Accepted properly, Author 2000",
    "canonicalName": "Accepted properly",
    "rank": "SPECIES",
    "taxonomicStatus": "ACCEPTED",
    "kingdom": "Animalia",
    "phylum": "Mollusca",
    "class": "",
    "order": "",
    "family": "",
    "genus": "Accepted",
}
SIBLING_ACCEPTED_HOMONYM = _gbif_match(
    usageKey=200,
    canonicalName="Old synonym name",
    status="ACCEPTED",
    kingdom="Plantae",
    genus="Unrelated",
)


def _gbif_synonym_of(accepted: dict, alternatives: list[dict]):
    synonym = _gbif_match(
        usageKey=100,
        canonicalName="Old synonym name",
        status="SYNONYM",
        synonym=True,
        acceptedUsageKey=999,
        kingdom="Animalia",
        alternatives=alternatives,
    )

    def handler(request):
        if "species/999" in str(request.url):
            return httpx.Response(200, json=accepted)
        return httpx.Response(200, json=synonym)

    return handler


@pytest.mark.parametrize(
    "alternatives", [[], [SIBLING_ACCEPTED_HOMONYM]], ids=["alone", "beside_an_accepted_homonym"]
)
def test_gbif_exact_synonym_follows_accepted_usage_key(alternatives):
    resolver = _gbif_resolver(_gbif_synonym_of(ACCEPTED_SPECIES, alternatives))
    result = resolver.resolve("Old synonym name", {"kingdom": "Animalia"})
    assert result.scientific_name == "Accepted properly"
    assert result.genus == "Accepted"
    assert result.aphia_id == ""
    assert result.gbif_usage_key == "999"
    assert result.taxon_concept_id == "https://www.gbif.org/species/999"
    assert result.review_reason == "gbif_synonym_resolved_to_accepted"


def test_gbif_synonym_follow_up_survives_explicit_nulls_in_the_species_record():
    accepted = {
        **ACCEPTED_SPECIES,
        "scientificName": None,
        "rank": None,
        "authorship": None,
        "class": None,
        "order": None,
        "family": None,
        "genus": None,
    }
    resolver = _gbif_resolver(_gbif_synonym_of(accepted, []))
    result = resolver.resolve("Old synonym name", {"kingdom": "Animalia"})
    assert result.scientific_name == "Accepted properly"
    assert result.class_ == ""
    assert result.family == ""
    assert result.genus == ""
    assert result.scientific_name_authorship == ""


def _source_id_resolver(by_id: dict, name_matches: list[dict]) -> TaxonResolver:
    def handler(request):
        if "AphiaRecordByAphiaID" in str(request.url):
            return httpx.Response(200, json=by_id)
        names = request.url.params.get_list("scientificnames[]")
        return httpx.Response(200, json=[name_matches for _ in names])

    return TaxonResolver(WormsClient(client=_client(handler)))


BIOTA_INCERTAE_SEDIS = _record(
    AphiaID=12, scientificname="Biota incertae sedis", kingdom="Biota incertae sedis"
)


def test_bare_aphia_id_also_recognized_as_source_taxon_id():
    resolver = _source_id_resolver(AAPTOS, [])
    result = resolver.resolve("anything", {}, source_taxon_id="132064")
    assert result.aphia_id == "132064"


def test_source_taxon_id_contradiction_is_disclosed_but_still_loses_to_the_id():
    resolver = _source_id_resolver(
        BIOTA_INCERTAE_SEDIS,
        [_record(AphiaID=999, scientificname="Clupea pallasii", kingdom="Animalia")],
    )
    result = resolver.resolve(
        "Clupea pallasii",
        {},
        source_taxon_id="urn:lsid:marinespecies.org:taxname:12",
    )
    assert result.aphia_id == "12"
    assert result.scientific_name == "Biota incertae sedis"
    assert _codes(result) == ["TAXON_ID_CONTRADICTS_SOURCE"]
    assert _log(result).findings[0].severity == "warning"
    assert "12" in result.review_reason
    assert result.needs_review
    assert "999" in result.review_reason
    assert "source_taxon_id" not in result.review_reason


def test_a_placeholder_name_beside_a_source_id_is_never_sent_to_worms():
    names_sent = []

    def handler(request):
        if "AphiaRecordByAphiaID" in str(request.url):
            return httpx.Response(200, json=BIOTA_INCERTAE_SEDIS)
        names_sent.extend(request.url.params.get_list("scientificnames[]"))
        return httpx.Response(200, json=[[]])

    resolver = TaxonResolver(WormsClient(client=_client(handler)))
    result = resolver.resolve(
        "Incertae sedis", {}, source_taxon_id="urn:lsid:marinespecies.org:taxname:12"
    )
    assert names_sent == []
    assert result.aphia_id == "12"
    assert _codes(result) == []
    assert not result.needs_review


def test_a_source_id_worms_could_not_check_is_kept_and_disclosed():
    def handler(request):
        if "AphiaRecordByAphiaID" in str(request.url):
            return httpx.Response(200, json=BIOTA_INCERTAE_SEDIS)
        return httpx.Response(503)

    resolver = TaxonResolver(WormsClient(client=_client(handler)))
    result = resolver.resolve(
        "Clupea pallasii", {}, source_taxon_id="urn:lsid:marinespecies.org:taxname:12"
    )
    assert result.aphia_id == "12"
    assert _codes(result) == ["TAXON_ID_UNCHECKED"]
    assert _log(result).findings[0].severity == "warning"
    assert result.needs_review
    assert result.review_reason == (
        "WoRMS didn't answer, so the source's taxon ID 12 wasn't checked against the name"
    )


def test_a_source_id_whose_accepted_id_is_the_name_match_is_no_contradiction():
    resolver = _source_id_resolver(
        _record(
            AphiaID=424812,
            scientificname="Phascolosoma agassizii",
            status="alternative representation",
            valid_AphiaID=266496,
            kingdom="Animalia",
        ),
        [_record(AphiaID=266496, scientificname="Phascolosoma agassizii", kingdom="Animalia")],
    )
    result = resolver.resolve("Phascolosoma agassizii", {}, source_taxon_id="424812")
    assert result.aphia_id == "424812"
    assert _log(result).findings == []
    assert not result.needs_review


def test_source_taxon_id_agreement_raises_no_contradiction_finding():
    resolver = _source_id_resolver(AAPTOS, [AAPTOS])
    result = resolver.resolve(
        "Aaptos", {}, source_taxon_id="urn:lsid:marinespecies.org:taxname:132064"
    )
    assert result.aphia_id == "132064"
    assert _log(result).findings == []


def test_source_taxon_id_cross_check_ignores_a_weak_name_based_match():
    resolver = _source_id_resolver(
        _record(AphiaID=12, scientificname="Aaptos", kingdom="Animalia"),
        [_record(AphiaID=999, scientificname="Aaptoss", match_type="fuzzy")],
    )
    result = resolver.resolve(
        "Aaptos", {}, source_taxon_id="urn:lsid:marinespecies.org:taxname:12"
    )
    assert result.aphia_id == "12"
    assert _log(result).findings == []


def test_ncbi_taxid_takes_precedence_over_gbif_usage_key():
    resolver = _gbif_resolver(
        _gbif_answering(usageKey=4321, canonicalName="Aaptos", kingdom="Animalia"),
        _refuse_worms,
        registers=("gbif",),
    )
    result = resolver.resolve("Aaptos", {"kingdom": "Animalia"}, ncbi_taxid="6544")
    assert result.scientific_name_id == "https://www.gbif.org/species/4321"
    assert result.taxon_concept_id == "NCBI:txid6544"


def _resolve_aaptos_with_ncbi_taxid(ncbi_taxid: str) -> ResolvedTaxon:
    return _resolver({"Aaptos": [AAPTOS]}).resolve(
        "Aaptos", {"kingdom": "Animalia"}, ncbi_taxid=ncbi_taxid
    )


@pytest.mark.parametrize(
    "ncbi_taxid", ["6544", "NCBI:txid6544", "00006544", "6544.0", "NCBI:txid006544"]
)
def test_an_ncbi_taxid_is_published_as_a_curie_without_leading_zeros_or_a_decimal_point(
    ncbi_taxid,
):
    assert _resolve_aaptos_with_ncbi_taxid(ncbi_taxid).taxon_concept_id == "NCBI:txid6544"


@pytest.mark.parametrize("ncbi_taxid", ["", "NA"])
def test_a_missing_ncbi_taxid_leaves_taxon_concept_id_untouched(ncbi_taxid):
    result = _resolve_aaptos_with_ncbi_taxid(ncbi_taxid)
    assert result.taxon_concept_id == ""
    assert _log(result).findings == []


@pytest.mark.parametrize("ncbi_taxid", ["txid65x", "0", "1", "131567", "NCBI:txid1", "000"])
def test_an_ncbi_taxid_that_names_no_taxon_is_left_out_and_reported(ncbi_taxid):
    result = _resolve_aaptos_with_ncbi_taxid(ncbi_taxid)
    assert result.taxon_concept_id == ""
    assert _codes(result) == ["NCBI_TAXID_MALFORMED"]
    assert repr(ncbi_taxid) in result.review_reason
    assert "ncbi_taxid" not in result.review_reason


def test_a_malformed_ncbi_taxid_on_a_gbif_name_reports_the_gbif_url_it_keeps():
    resolver = _gbif_resolver(_gbif_answering(usageKey=4321, canonicalName="Microtrichaceae"))
    result = resolver.resolve("Microtrichaceae", {}, ncbi_taxid="txid65x")
    assert result.taxon_concept_id == "https://www.gbif.org/species/4321"
    assert result.taxon_concept_id in result.review_reason


def test_an_aphia_id_of_zero_is_not_looked_up():
    names_only = _worms_transport({"Aaptos": [AAPTOS]})

    def handler(request):
        if "AphiaRecordByAphiaID" in str(request.url):
            raise AssertionError("AphiaID 0 was looked up")
        return names_only(request)

    resolver = TaxonResolver(WormsClient(client=_client(handler)))
    result = resolver.resolve("Aaptos", {}, source_taxon_id="0")
    assert result.aphia_id == "132064"


def test_taxon_unresolved_aggregates_every_row_into_one_finding():
    resolver = _resolver({})
    log = _log(resolver.resolve("Totally madeupii", {}), resolver.resolve("Also madeupii", {}))
    assert len(log.findings) == 1
    assert log.findings[0].count == 2


def test_each_resolution_carries_only_its_own_findings():
    resolver = _resolver({"Aaptos": [AAPTOS]})
    assert resolver.resolve("Totally madeupii", {}).findings == ["TAXON_UNRESOLVED"]
    assert resolver.resolve("Aaptos", {}).findings == []


def test_taxon_fuzzy_is_disclosed_when_a_non_confident_match_is_kept():
    resolver = _resolver({"Aaptos": [{**AAPTOS, "match_type": "fuzzy"}]})
    result = resolver.resolve("Aaptos", {"kingdom": "Animalia"})
    assert result.review_reason == "non_confident_match_type:fuzzy"
    assert _codes(result) == ["TAXON_FUZZY"]


def test_taxon_rejected_kingdom_is_disclosed_when_a_non_confident_candidate_is_rejected():
    weirdname = _record(
        AphiaID=1, scientificname="Weirdname", kingdom="Bacteria", match_type="fuzzy"
    )
    resolver = _resolver({"Weirdname": [weirdname], "Aaptos": [AAPTOS]})
    result = resolver.resolve("Weirdname", {"kingdom": "Animalia", "genus": "Aaptos"})
    assert result.aphia_id == "132064"
    assert _codes(result) == ["TAXON_REJECTED_KINGDOM"]
    assert _log(result).findings[0].count == 1


def test_gbif_fuzzy_kept_match_is_disclosed():
    resolver = _gbif_resolver(
        _gbif_answering(kingdom="Animalia", matchType="FUZZY", status="ACCEPTED")
    )
    result = resolver.resolve("Someveryfuzzy", {"kingdom": "Animalia"})
    assert result.review_reason == "non_confident_match_type:FUZZY"
    assert _codes(result) == ["TAXON_FUZZY"]


_NON_CONFIDENT_ROWS = [
    (
        "Marinimicrobia (SAR406 clade)",
        {"kingdom": "Bacteria"},
        {
            "Marinimicrobia": [
                _record(
                    AphiaID=394115,
                    scientificname="Marinimicrobium",
                    rank="Genus",
                    match_type="near_2",
                    kingdom="Bacteria",
                    genus="Marinimicrobium",
                )
            ],
            "Bacteria": [
                _record(AphiaID=6, scientificname="Bacteria", rank="Kingdom", kingdom="Bacteria")
            ],
        },
        "Marinimicrobium",
        "Bacteria",
    ),
    (
        "Desulfocapsaceae",
        {"kingdom": "Bacteria", "order": "Desulfobacterales", "family": "Desulfocapsaceae"},
        {
            "Desulfocapsaceae": [
                _record(
                    AphiaID=570220,
                    scientificname="Desulfobulbus",
                    rank="Genus",
                    match_type="near_2",
                    kingdom="Bacteria",
                    genus="Desulfobulbus",
                )
            ],
            "Desulfobacterales": [
                _record(
                    AphiaID=570219,
                    scientificname="Desulfobacterales",
                    rank="Order",
                    kingdom="Bacteria",
                    order="Desulfobacterales",
                )
            ],
        },
        "Desulfobulbus",
        "Desulfobacterales",
    ),
    (
        "Sva0996_marine_group",
        {"kingdom": "Bacteria", "phylum": "Actinobacteriota", "family": "Microtrichaceae"},
        {
            "Sva0996_marine_group": [
                _record(
                    AphiaID=571800,
                    scientificname="Acidimicrobium",
                    rank="Genus",
                    match_type="near_2",
                    kingdom="Bacteria",
                    genus="Acidimicrobium",
                )
            ],
            "Microtrichaceae": [
                _record(
                    AphiaID=571800,
                    scientificname="Acidimicrobium",
                    rank="Genus",
                    match_type="near_2",
                    kingdom="Bacteria",
                    genus="Acidimicrobium",
                )
            ],
            "Actinobacteriota": [
                _record(
                    AphiaID=571799,
                    scientificname="Actinobacteriota",
                    rank="Phylum",
                    kingdom="Bacteria",
                    phylum="Actinobacteriota",
                )
            ],
        },
        "Acidimicrobium",
        "Actinobacteriota",
    ),
    (
        "Porticoccus",
        {"kingdom": "Bacteria", "order": "Cellvibrionales"},
        {
            "Porticoccus": [
                _record(
                    AphiaID=571974,
                    scientificname="Ponticoccus",
                    rank="Genus",
                    match_type="near_1",
                    kingdom="Bacteria",
                    genus="Ponticoccus",
                ),
                _record(
                    AphiaID=162721,
                    scientificname="Protococcus",
                    rank="Genus",
                    match_type="near_2",
                    status="unaccepted",
                    kingdom="Plantae",
                    genus="Protococcus",
                ),
            ],
            "Cellvibrionales": [
                _record(
                    AphiaID=571900,
                    scientificname="Cellvibrionales",
                    rank="Order",
                    kingdom="Bacteria",
                    order="Cellvibrionales",
                )
            ],
        },
        "Ponticoccus",
        "Cellvibrionales",
    ),
    (
        "Blfdi19",
        {"kingdom": "Bacteria"},
        {
            "Blfdi19": [
                _record(
                    AphiaID=571500,
                    scientificname="Polyangium",
                    rank="Genus",
                    match_type="near_2",
                    kingdom="Bacteria",
                    genus="Polyangium",
                )
            ],
            "Bacteria": [
                _record(AphiaID=6, scientificname="Bacteria", rank="Kingdom", kingdom="Bacteria")
            ],
        },
        "Polyangium",
        "Bacteria",
    ),
    (
        "Austrarchaea sp. QLD",
        {"kingdom": "Animalia", "phylum": "Arthropoda"},
        {
            "Austrarchaea": [
                _record(
                    AphiaID=212,
                    scientificname="Arcidae",
                    rank="Family",
                    match_type="phonetic",
                    kingdom="Animalia",
                    phylum="Mollusca",
                    family="Arcidae",
                )
            ],
            "Arthropoda": [
                _record(
                    AphiaID=1065,
                    scientificname="Arthropoda",
                    rank="Phylum",
                    kingdom="Animalia",
                    phylum="Arthropoda",
                )
            ],
        },
        "Arcidae",
        "Arthropoda",
    ),
]


@pytest.mark.parametrize(
    "terminal_name,source_ranks,records,published,ancestor",
    _NON_CONFIDENT_ROWS,
    ids=[row[0] for row in _NON_CONFIDENT_ROWS],
)
def test_lone_non_confident_match_is_published_by_default(
    terminal_name, source_ranks, records, published, ancestor
):
    del ancestor
    resolver = _resolver(records)
    result = resolver.resolve(terminal_name, source_ranks)
    assert result.scientific_name == published
    assert result.needs_review is True
    assert "TAXON_FUZZY" in set(_codes(result))


@pytest.mark.parametrize(
    "terminal_name,source_ranks,records,published,ancestor",
    _NON_CONFIDENT_ROWS,
    ids=[row[0] for row in _NON_CONFIDENT_ROWS],
)
def test_require_confident_backs_off_past_a_non_confident_match(
    terminal_name, source_ranks, records, published, ancestor
):
    del published
    resolver = _resolver(records, require_confident=True)
    result = resolver.resolve(terminal_name, source_ranks)
    assert result.scientific_name == ancestor
    assert result.resolution_path == "rank_backoff"
    assert result.needs_review is False
    codes = set(_codes(result))
    assert "TAXON_FUZZY" not in codes
    assert "TAXON_FUZZY_REJECTED" in codes


def test_require_confident_still_accepts_an_exact_replaced_match():
    resolver = _resolver(
        {"Aaptos": [{**AAPTOS, "match_type": "exact_replaced"}]}, require_confident=True
    )
    result = resolver.resolve("Aaptos", {"kingdom": "Animalia"})
    assert result.scientific_name == "Aaptos"
    assert result.resolution_path == "leaf"
    assert result.needs_review is False


def test_require_confident_leaves_an_unaccepted_status_match_alone():
    resolver = _resolver({"Aaptos": [{**AAPTOS, "status": "unaccepted"}]}, require_confident=True)
    result = resolver.resolve("Aaptos", {"kingdom": "Animalia"})
    assert result.scientific_name == "Aaptos"
    assert result.needs_review is True
    assert result.review_reason == "unaccepted_status:unaccepted"


PONTICOCCUS_UNACCEPTED = _record(
    AphiaID=571974,
    scientificname="Ponticoccus",
    rank="Genus",
    match_type="near_1",
    status="unaccepted",
    kingdom="Bacteria",
    genus="Ponticoccus",
)
CELLVIBRIONALES = _record(
    AphiaID=571900,
    scientificname="Cellvibrionales",
    rank="Order",
    kingdom="Bacteria",
    order="Cellvibrionales",
)


def test_require_confident_refuses_a_near_match_to_an_unaccepted_name():
    records = {"Porticoccus": [PONTICOCCUS_UNACCEPTED], "Cellvibrionales": [CELLVIBRIONALES]}
    resolver = _resolver(records, require_confident=True)
    result = resolver.resolve("Porticoccus", {"kingdom": "Bacteria", "order": "Cellvibrionales"})
    assert result.scientific_name == "Cellvibrionales"
    assert result.resolution_path == "rank_backoff"
    assert "TAXON_FUZZY_REJECTED" in _codes(result)


def test_a_near_match_to_an_unaccepted_name_discloses_both_problems():
    result = _resolver({"Porticoccus": [PONTICOCCUS_UNACCEPTED]}).resolve(
        "Porticoccus", {"kingdom": "Bacteria"}
    )
    assert result.scientific_name == "Ponticoccus"
    assert result.review_reason == "non_confident_match_type:near_1,unaccepted_status:unaccepted"
    assert "TAXON_FUZZY" in _codes(result)


def _gbif_aaptos(match_type: str, status: str):
    return _gbif_answering(
        canonicalName="Aaptos",
        kingdom="Animalia",
        genus="Aaptos",
        matchType=match_type,
        status=status,
    )


def test_require_confident_keeps_a_confident_gbif_match_that_gbif_doubts():
    resolver = _gbif_resolver(_gbif_aaptos("EXACT", "DOUBTFUL"), require_confident=True)
    result = resolver.resolve("Aaptos", {"kingdom": "Animalia"})
    assert result.scientific_name == "Aaptos"
    assert result.needs_review is True
    assert result.review_reason == "gbif_status:DOUBTFUL"
    assert "TAXON_FUZZY_REJECTED" not in _codes(result)


def test_require_confident_still_refuses_a_fuzzy_gbif_match():
    resolver = _gbif_resolver(_gbif_aaptos("FUZZY", "ACCEPTED"), require_confident=True)
    result = resolver.resolve("Aaptos", {"kingdom": "Animalia"})
    assert result.resolution_path == "biota_fallback"
    assert "TAXON_FUZZY_REJECTED" in _codes(result)


def test_a_fuzzy_and_doubtful_gbif_match_discloses_both_problems():
    result = _gbif_resolver(_gbif_aaptos("FUZZY", "DOUBTFUL")).resolve(
        "Aaptos", {"kingdom": "Animalia"}
    )
    assert result.review_reason == "non_confident_match_type:FUZZY,gbif_status:DOUBTFUL"


def test_confident_requirement_holds_at_every_rank_the_backoff_visits():
    wrongia = _record(
        AphiaID=999,
        scientificname="Wrongia",
        rank="Genus",
        match_type="near_2",
        kingdom="Animalia",
        genus="Wrongia",
    )
    resolver = _resolver({"Sometaxon": [], "Somefamilia": [wrongia]})
    result = resolver.resolve("Sometaxon", {"kingdom": "Eukaryota", "family": "Somefamilia"})
    assert result.scientific_name != "Wrongia"
    assert result.resolution_path == "biota_fallback"
    codes = _codes(result)
    assert "TAXON_FUZZY" not in codes
    assert "TAXON_FUZZY_REJECTED" in codes


def test_an_uninformative_source_kingdom_is_disclosed():
    resolver = _resolver({})
    log = _log(
        resolver.resolve("Sometaxon", {"kingdom": "Eukaryota"}),
        resolver.resolve("Othertaxon", {"kingdom": "Animalia"}),
    )
    uninformative = [f for f in log.findings if f.code == "SOURCE_KINGDOM_UNINFORMATIVE"]
    assert len(uninformative) == 1
    assert uninformative[0].count == 1


def test_an_organelle_marker_is_still_rejected_on_the_uninformative_path():
    result = _resolver(CHLOROPLAST_RECORDS).resolve(
        "Prasinoderma coloniale",
        {"kingdom": "Eukaryota", "phylum": "Cyanobacteria", "genus": "Chloroplast"},
    )
    assert result.kingdom != "Plantae"
    assert result.resolution_path == "biota_fallback"


BACTEROIDOTA = {
    "AphiaID": 100,
    "scientificname": "Bacteroidota",
    "rank": "Phylum",
    "kingdom": "Bacteria",
    "phylum": "Bacteroidota",
}


@pytest.mark.parametrize("terminal", ["uncultured bacterium", "sp."])
def test_a_placeholder_terminal_backs_off_to_the_phylum_its_own_lineage_carries(terminal):
    sent: list[str] = []
    resolver = _resolver({"Bacteroidota": [_record(**BACTEROIDOTA)]}, sent=sent)

    result = resolver.resolve(terminal, {"kingdom": "Bacteria", "phylum": "Bacteroidota"})

    assert result.scientific_name == "Bacteroidota"
    assert result.resolution_path == "rank_backoff"
    assert sent == ["Bacteroidota"]


def test_two_lineages_differing_only_in_their_junk_species_token_resolve_alike():
    records = {"Chloroflexi": [_record(AphiaID=200, scientificname="Chloroflexi", rank="Phylum")]}
    source_ranks = {
        "kingdom": "Bacteria",
        "phylum": "Chloroflexi",
        "class": "Dehalococcoidia",
        "order": "SAR202_clade",
        "family": "SAR202_clade",
        "genus": "SAR202_clade",
    }

    unmatched = _resolver(records).resolve("hydrothermal_vent", source_ranks)
    placeholder = _resolver(records).resolve("marine_metagenome", source_ranks)

    assert placeholder.to_row() == unmatched.to_row()
    assert placeholder.scientific_name == "Chloroflexi"


def test_a_placeholder_terminal_over_placeholder_ranks_queries_nothing():
    sent: list[str] = []
    resolver = _resolver({}, sent=sent)

    result = resolver.resolve(
        "unassigned", {"kingdom": "unassigned", "phylum": "uncultured", "genus": "sp."}
    )

    assert sent == []
    assert result.resolution_path == "incertae_sedis_placeholder"
    assert result.kingdom == "Biota incertae sedis"


def test_an_empty_terminal_skips_a_placeholder_rank_the_way_a_placeholder_terminal_does():
    sent: list[str] = []
    resolver = _resolver({"Bacteroidota": [_record(**BACTEROIDOTA)]}, sent=sent)

    result = resolver.resolve(
        "", {"kingdom": "Bacteria", "genus": "uncultured", "phylum": "Bacteroidota"}
    )

    assert sent == ["Bacteroidota"]
    assert result.scientific_name == "Bacteroidota"


_BD2_RANKS = {
    "kingdom": "Bacteria",
    "phylum": "Bacteroidota",
    "class": "Bacteroidia",
    "order": "Bacteroidales",
}
_BD2_RECORDS = {
    "Bacteroidetes BD2-2": [
        _record(
            AphiaID=559326,
            scientificname="Bacteroidetes",
            rank="Phylum",
            kingdom="Bacteria",
            phylum="Bacteroidetes",
        )
    ],
    "Bacteroidales": [
        _record(
            AphiaID=570491,
            scientificname="Bacteroidales",
            rank="Order",
            kingdom="Bacteria",
            phylum="Bacteroidetes",
            order="Bacteroidales",
        )
    ],
}


def test_require_confident_refuses_an_exact_match_on_a_different_name():
    resolver = _resolver(_BD2_RECORDS, require_confident=True)
    result = resolver.resolve("Bacteroidetes BD2-2", _BD2_RANKS)
    assert result.scientific_name == "Bacteroidales"
    assert result.resolution_path == "rank_backoff"
    assert "TAXON_FUZZY_REJECTED" in set(_codes(result))


def test_an_exact_match_on_a_different_name_is_flagged_for_review():
    resolver = _resolver(_BD2_RECORDS)
    result = resolver.resolve("Bacteroidetes BD2-2", _BD2_RANKS)
    assert result.scientific_name == "Bacteroidetes"
    assert result.needs_review is True
    assert result.review_reason == "name_mismatch:Bacteroidetes"


def test_an_exact_subgenus_match_still_counts_as_confident():
    records = {
        "Acartia tonsa": [
            _record(
                AphiaID=345943,
                scientificname="Acartia (Acanthacartia) tonsa",
                match_type="exact_subgenus",
                kingdom="Animalia",
                genus="Acartia",
            )
        ]
    }
    resolver = _resolver(records, require_confident=True)
    result = resolver.resolve("Acartia tonsa", {"kingdom": "Animalia"})
    assert result.scientific_name == "Acartia (Acanthacartia) tonsa"
    assert result.resolution_path == "leaf"


def test_require_confident_refuses_a_gbif_exact_match_on_a_different_name():
    resolver = _gbif_resolver(
        _gbif_answering(canonicalName="Bacteroidetes", kingdom="Bacteria"), require_confident=True
    )
    result = resolver.resolve("Bacteroidetes BD2-2", {"kingdom": "Bacteria"})
    assert result.scientific_name != "Bacteroidetes"


def test_an_underscore_joined_binomial_matches_its_spaced_name_confidently():
    records = {
        "Mytilus edulis": [
            _record(AphiaID=140480, scientificname="Mytilus edulis", kingdom="Animalia")
        ]
    }
    resolver = _resolver(records, require_confident=True)
    result = resolver.resolve("Mytilus_edulis", {"kingdom": "Animalia"})
    assert result.scientific_name == "Mytilus edulis"
    assert result.resolution_path == "leaf"
    assert result.needs_review is False


def test_source_taxon_id_cross_check_ignores_an_exact_match_on_a_different_name():
    resolver = _source_id_resolver(
        _record(AphiaID=12, scientificname="Bacteroidetes BD2-2", kingdom="Bacteria"),
        [_record(AphiaID=559326, scientificname="Bacteroidetes", kingdom="Bacteria")],
    )
    result = resolver.resolve(
        "Bacteroidetes BD2-2", {}, source_taxon_id="urn:lsid:marinespecies.org:taxname:12"
    )
    assert result.aphia_id == "12"
    assert _log(result).findings == []


def test_a_rank_backoff_that_gbif_resolves_is_labelled_rank_backoff():
    def gbif_handler(request):
        if request.url.params.get("name") == "Aaptos":
            return httpx.Response(
                200, json=_gbif_match(canonicalName="Aaptos", kingdom="Animalia", genus="Aaptos")
            )
        return httpx.Response(200, json={"matchType": "NONE", "confidence": 100})

    resolver = _gbif_resolver(gbif_handler)
    result = resolver.resolve("Nonexistentus madeupii", {"kingdom": "Animalia", "genus": "Aaptos"})
    assert result.scientific_name == "Aaptos"
    assert result.authority == "gbif"
    assert result.resolution_path == "rank_backoff"


GBIF_INSECT_GENUS_NAMED_GENUS = _gbif_match(
    usageKey=8513230,
    scientificName="Genus Becker, 1907",
    canonicalName="Genus",
    rank="GENUS",
    kingdom="Animalia",
    phylum="Arthropoda",
    order="Diptera",
    family="Milichiidae",
    genus="Genus",
)


MAMIELLACEAE = _record(AphiaID=17637, scientificname="Mamiellaceae")


def _rank_word_resolver(sent: list[str]) -> TaxonResolver:
    def gbif(request):
        name = request.url.params.get("name")
        sent.append(name)
        if name == "Genus":
            return httpx.Response(200, json=GBIF_INSECT_GENUS_NAMED_GENUS)
        return httpx.Response(200, json={"matchType": "NONE", "confidence": 100})

    return _gbif_resolver(gbif, _worms_transport({"Mamiellaceae": [MAMIELLACEAE]}, sent))


@pytest.mark.parametrize("terminal", ["Genus", "species", "ORDER", "Species:", " Kingdom "])
def test_a_bare_rank_word_is_never_sent_to_a_register(terminal):
    sent: list[str] = []
    resolver = _rank_word_resolver(sent)
    resolver.prefetch([{"lineage_key": "k", "terminal_name": terminal}])

    result = resolver.resolve(terminal, {})

    assert sent == []
    assert result.scientific_name == "Biota incertae sedis"
    (finding,) = _log(result).findings
    assert finding.code == "TAXON_RANK_WORD_REFUSED"
    assert "rank word" in finding.message
    assert "taxonomy column" in finding.message
    assert "resolve-taxonomy" in finding.message


def test_a_rank_word_terminal_backs_off_to_the_ranks_its_lineage_names():
    sent: list[str] = []
    resolver = _rank_word_resolver(sent)

    result = resolver.resolve("Genus", {"genus": "Genus", "family": "Mamiellaceae"})

    assert sent == ["Mamiellaceae"]
    assert result.scientific_name == "Mamiellaceae"
    assert result.findings == ["TAXON_RANK_WORD_REFUSED"]


def test_a_rank_word_in_a_source_rank_is_skipped_by_the_backoff():
    sent: list[str] = []
    resolver = _rank_word_resolver(sent)

    resolver.resolve("Nonexistentus madeupii", {"genus": "Genus", "family": "Mamiellaceae"})

    assert sent == ["Nonexistentus madeupii", "Nonexistentus madeupii", "Mamiellaceae"]


def test_a_rank_word_in_a_compound_name_is_never_sent():
    sent: list[str] = []
    resolver = _rank_word_resolver(sent)

    result = resolver.resolve("Genus | Species", {})

    assert sent == []
    assert "TAXON_RANK_WORD_REFUSED" in result.findings


def test_a_rank_word_beside_a_source_taxon_id_is_never_sent():
    sent: list[str] = []

    names_only = _worms_transport({}, sent)

    def worms(request):
        if "AphiaRecordByAphiaID" in request.url.path:
            return httpx.Response(200, json=MAMIELLACEAE)
        return names_only(request)

    resolver = TaxonResolver(WormsClient(client=_client(worms)))

    result = resolver.resolve("Genus", {}, source_taxon_id="17637")

    assert sent == []
    assert result.aphia_id == "17637"


def test_a_rank_word_in_an_unranked_lineage_is_refused():
    sent: list[str] = []
    resolver = _rank_word_resolver(sent)

    result = resolver.resolve("Nonexistentus madeupii", {}, unranked=("Mamiellaceae", "Genus"))

    assert "Genus" not in sent
    assert result.findings == ["TAXON_RANK_WORD_REFUSED"]


def test_a_real_name_containing_a_rank_word_is_still_looked_up():
    sent: list[str] = []
    resolver = _rank_word_resolver(sent)

    resolver.resolve("Ordericalis", {})

    assert sent[0] == "Ordericalis"


def _lineage(key: str, terminal: str, **source_ranks: str) -> dict[str, str]:
    row = {"lineage_key": key, "terminal_name": terminal}
    row.update({f"source_{rank}": name for rank, name in source_ranks.items()})
    return row


def _locked(key: str, name: str) -> dict[str, str]:
    return {"lineage_key": key, "scientificName": name, "scientificNameID": f"id:{name}"}


def _collapsed(pairs: list[tuple[dict[str, str], str]]) -> set[str]:
    lineages = [lineage for lineage, _ in pairs]
    locks = [_locked(lineage["lineage_key"], name) for lineage, name in pairs]
    return mass_collapsed_keys(lineages, locks)


def test_five_differently_named_lineages_landing_on_a_foreign_taxon_are_flagged():
    names = ["Micromonas pusilla", "Homo sapiens", "Balanus", "Pugettia producta", "Aglaophenia"]
    pairs = [(_lineage(f"k{i}", name), "Genus") for i, name in enumerate(names)]
    assert _collapsed(pairs) == {"k0", "k1", "k2", "k3", "k4"}


def test_four_differently_named_lineages_on_one_foreign_taxon_are_not_flagged():
    names = ["Micromonas pusilla", "Homo sapiens", "Balanus", "Pugettia producta"]
    pairs = [(_lineage(f"k{i}", name), "Genus") for i, name in enumerate(names)]
    assert _collapsed(pairs) == set()


def test_rank_backoff_to_a_name_each_lineage_carries_is_not_a_collapse():
    pairs = [
        (_lineage(f"k{i}", f"Micromonas sp{i}", genus="Micromonas"), "Micromonas")
        for i in range(50)
    ]
    assert _collapsed(pairs) == set()


def test_many_lineages_ending_at_the_placeholder_taxon_are_not_a_collapse():
    pairs = [(_lineage(f"k{i}", f"Madeup name{i}"), "Biota incertae sedis") for i in range(50)]
    assert _collapsed(pairs) == set()


def test_lineages_landing_on_different_taxa_without_identifiers_are_not_a_collapse():
    lineages = [_lineage(f"k{i}", f"Madeup name{i}") for i in range(5)]
    locks = [
        {"lineage_key": f"k{i}", "scientificName": f"Other taxon{i}", "scientificNameID": ""}
        for i in range(5)
    ]
    assert mass_collapsed_keys(lineages, locks) == set()


def test_one_name_in_many_lineages_counts_once():
    pairs = [(_lineage(f"k{i}", "Micromonas pusilla"), "Genus") for i in range(10)]
    assert _collapsed(pairs) == set()


CYANOBIUM_ABOVE = (
    "Bacteria",
    "Cyanobacteria",
    "Cyanobiia",
    "Synechococcales",
    "Prochlorococcaceae",
)
SYNECHOCOCCALES = {
    "AphiaID": 146551,
    "scientificname": "Synechococcales",
    "rank": "Order",
    "kingdom": "Bacteria",
    "phylum": "Cyanobacteria",
}


def test_an_unranked_lineage_backs_off_through_its_names_deepest_first():
    sent: list[str] = []
    resolver = _resolver({"Synechococcales": [_record(**SYNECHOCOCCALES)]}, sent=sent)

    result = resolver.resolve("Cyanobium_PCC-6307", {}, unranked=CYANOBIUM_ABOVE)

    assert sent == ["Prochlorococcaceae", "Synechococcales"]
    assert result.scientific_name == "Synechococcales"
    assert result.resolution_path == "rank_backoff"
    assert result.findings == []


def test_an_unranked_lineage_never_sends_a_clade_label_or_rank_word_placeholder():
    sent: list[str] = []
    resolver = _resolver({}, sent=sent)

    resolver.resolve(
        "Clade_Ia", {}, unranked=("Bacteria", "Pelagibacterales", "SAR11_clade", "order_X")
    )

    assert sent == ["Pelagibacterales", "Bacteria"]


def test_a_placeholder_rank_is_never_sent_after_a_real_terminal_name_misses():
    sent: list[str] = []
    resolver = _resolver({"Bacteroidota": [_record(**BACTEROIDOTA)]}, sent=sent)

    result = resolver.resolve(
        "Nomatch species", {"genus": "incertae sedis", "phylum": "Bacteroidota"}
    )

    assert sent == ["Nomatch species", "Bacteroidota"]
    assert result.scientific_name == "Bacteroidota"


def test_a_terminal_name_with_an_underscore_is_never_sent_and_backs_off():
    sent: list[str] = []
    resolver = _resolver(_BD2_RECORDS, sent=sent)

    result = resolver.resolve("Bacteroidetes_BD2-2", _BD2_RANKS)

    assert sent == ["Bacteroidales"]
    assert result.scientific_name == "Bacteroidales"
    assert result.resolution_path == "rank_backoff"
    assert result.findings == []


def test_a_placeholder_terminal_backs_off_through_its_unranked_lineage():
    sent: list[str] = []
    resolver = _resolver({"Bacteroidota": [_record(**BACTEROIDOTA)]}, sent=sent)

    result = resolver.resolve("", {}, unranked=("Bacteria", "Bacteroidota"))

    assert sent == ["Bacteroidota"]
    assert result.scientific_name == "Bacteroidota"


def test_an_unranked_lineage_that_names_a_kingdom_first_is_checked_against_it():
    resolver = _resolver(
        {
            "Diplosphaera": [
                _record(AphiaID=600760, scientificname="Diplosphaera", kingdom="Plantae")
            ],
            "Opitutaceae": [
                _record(AphiaID=570590, scientificname="Opitutaceae", kingdom="Bacteria")
            ],
        }
    )

    result = resolver.resolve(
        "Diplosphaera", {}, unranked=("Bacteria", "Verrucomicrobiota", "Opitutaceae")
    )

    assert result.scientific_name == "Opitutaceae"
    assert result.findings == ["TAXON_REJECTED_KINGDOM"]


def test_an_unranked_eukaryote_lineage_requires_a_confident_match():
    resolver = _resolver(
        {
            "MALV-II": [_record(AphiaID=1, scientificname="Malvales", match_type="fuzzy")],
            "Dinoflagellata": [
                _record(AphiaID=146203, scientificname="Dinoflagellata", kingdom="Chromista")
            ],
        }
    )

    result = resolver.resolve(
        "MALV-II", {}, unranked=("Eukaryota", "Alveolata", "Dinoflagellata", "core-syndiniales")
    )

    assert result.scientific_name == "Dinoflagellata"
    assert "SOURCE_KINGDOM_UNINFORMATIVE" in result.findings


DIPLOSPHAERA_RANKS = {"kingdom": "Bacteria", "family": "Opitutaceae", "genus": "Diplosphaera"}


def test_a_confident_worms_match_from_the_wrong_kingdom_is_rejected():
    resolver = _resolver(
        {
            "Diplosphaera": [
                _record(AphiaID=600760, scientificname="Diplosphaera", kingdom="Plantae")
            ],
            "Opitutaceae": [
                _record(AphiaID=570590, scientificname="Opitutaceae", kingdom="Bacteria")
            ],
        }
    )

    result = resolver.resolve("Diplosphaera", DIPLOSPHAERA_RANKS)

    assert result.scientific_name == "Opitutaceae"
    assert result.resolution_path == "rank_backoff"
    assert result.needs_review is False
    assert "TAXON_REJECTED_KINGDOM" in result.findings


def test_a_confident_gbif_match_from_the_wrong_kingdom_is_rejected():
    resolver = _gbif_resolver(
        _gbif_answering(canonicalName="Diplosphaera", kingdom="Plantae"),
        _refuse_worms,
        registers=("gbif",),
    )

    result = resolver.resolve("Diplosphaera", {"kingdom": "Bacteria"})

    assert result.resolution_path == "biota_fallback"
    assert "TAXON_REJECTED_KINGDOM" in result.findings


def test_a_confident_match_in_another_eukaryote_kingdom_is_accepted():
    resolver = _resolver(
        {
            "Fucus": [
                _record(AphiaID=144001, scientificname="Fucus", rank="Genus", kingdom="Chromista")
            ]
        }
    )

    result = resolver.resolve("Fucus", {"kingdom": "Plantae", "genus": "Fucus"})

    assert result.aphia_id == "144001"
    assert result.resolution_path == "leaf"
    assert result.findings == []


def test_a_non_confident_match_in_another_eukaryote_kingdom_is_still_rejected():
    resolver = _resolver(
        {
            "Fucus": [
                _record(
                    AphiaID=144001, scientificname="Fucus", kingdom="Chromista", match_type="fuzzy"
                )
            ]
        }
    )

    result = resolver.resolve("Fucus", {"kingdom": "Plantae"})

    assert result.resolution_path == "biota_fallback"
    assert "TAXON_REJECTED_KINGDOM" in result.findings


def test_a_confident_gbif_match_in_another_eukaryote_kingdom_is_accepted():
    resolver = _gbif_resolver(
        _gbif_answering(usageKey=7, canonicalName="Fucus", kingdom="Chromista"),
        _refuse_worms,
        registers=("gbif",),
    )

    result = resolver.resolve("Fucus", {"kingdom": "Plantae"})

    assert result.gbif_usage_key == "7"
    assert result.findings == []


def test_backoff_to_a_name_an_unranked_lineage_carries_is_not_a_collapse():
    lineages = [
        {
            "lineage_key": f"k{i}",
            "terminal_name": f"MALV-II-clade-{i}",
            "unranked_lineage": "Eukaryota;Alveolata;Dinoflagellata",
        }
        for i in range(5)
    ]
    locks = [_locked(lineage["lineage_key"], "Dinoflagellata") for lineage in lineages]
    assert mass_collapsed_keys(lineages, locks) == set()


def test_resolve_taxonomy_waits_the_register_timeout_for_each_request(monkeypatch):
    timeouts = []
    real_client = httpx.Client

    def recording_client(*args, timeout, **kwargs):
        timeouts.append(timeout)
        return real_client(*args, timeout=timeout, **kwargs)

    monkeypatch.setattr(httpx, "Client", recording_client)

    register_clients(None)(TaxonomySettings(registers=("worms", "gbif")))

    assert timeouts == [TIMEOUT, TIMEOUT]


FAMILIES = ("Suberitidae", "Acartiidae", "Rajidae")
GENERA = ("Aaptos", "Acartia", "Leucoraja", "Mytilus", "Nereis")


def _lineage_rows(count: int = 3 * BATCH_SIZE) -> list[dict[str, str]]:
    return [
        {
            "lineage_key": f"k{i}",
            "terminal_name": f"Genus{i} species{i}",
            "source_kingdom": "Animalia",
            "source_phylum": "Porifera",
            "source_class": "Demospongiae",
            "source_order": "Suberitida",
            "source_family": FAMILIES[i % len(FAMILIES)],
            "source_genus": GENERA[i % len(GENERA)],
            "row_count": "1",
            "ncbi_taxid": "",
            "source_taxon_id": "",
        }
        for i in range(count)
    ]


def _batches_for(rows: list[dict[str, str]]) -> int:
    return math.ceil(len({row["terminal_name"] for row in rows}) / BATCH_SIZE)


def _matches_terminal_names(request):
    names = request.url.params.get_list("scientificnames[]")
    return httpx.Response(
        200,
        json=[
            [_record(scientificname=name, kingdom="Animalia", genus=name.split()[0])]
            if name.startswith("Genus")
            else []
            for name in names
        ],
    )


def _prefetching_resolver(sent: list[str] | None = None) -> TaxonResolver:
    def handler(request):
        if sent is not None:
            sent.extend(request.url.params.get_list("scientificnames[]"))
        return _matches_terminal_names(request)

    return TaxonResolver(WormsClient(client=_client(handler)))


def _sent_by_prefetch(rows: list[dict[str, str]]) -> list[str]:
    sent: list[str] = []
    _prefetching_resolver(sent).prefetch(rows)
    return sent


def test_prefetch_makes_the_request_count_follow_the_batch_ceiling_not_the_lineage_count():
    rows = _lineage_rows()

    def resolve_every_row(resolver: TaxonResolver) -> None:
        for row in rows:
            ranks = {rank: row[f"source_{rank}"] for rank in RANKS_FROM_GENUS_UP}
            resolver.resolve(row["terminal_name"], ranks)

    resolve_every_row(_prefetching_resolver())
    assert api_usage.counts()["worms_match"] == len(rows)

    api_usage.reset()
    resolver = _prefetching_resolver()
    resolver.prefetch(rows)
    resolve_every_row(resolver)
    assert api_usage.counts()["worms_match"] == _batches_for(rows) < len(rows)


@pytest.mark.parametrize(
    "placeholder", ["", "  ", "sp.", "Unassigned", "incertae sedis", "uncultured bacterium"]
)
def test_prefetch_never_sends_a_terminal_name_resolve_would_refuse_to_send(placeholder):
    rows = _lineage_rows(count=1)
    rows[0].update({f"source_{rank}": placeholder for rank in RANKS_FROM_GENUS_UP})
    rows[0]["terminal_name"] = placeholder

    assert _sent_by_prefetch(rows) == []


def test_prefetch_sends_each_part_of_a_compound_name_expanded_with_its_genus():
    rows = _lineage_rows(count=1)
    rows[0]["terminal_name"] = "Leucoraja ocellata or erinacea"
    rows[0].update({f"source_{rank}": "" for rank in RANKS_FROM_GENUS_UP})

    assert _sent_by_prefetch(rows) == ["Leucoraja ocellata", "Leucoraja erinacea"]


def test_prefetch_skips_the_rank_columns_of_a_row_whose_terminal_name_matched():
    rows = _lineage_rows()

    sent = _sent_by_prefetch(rows)

    assert sorted(sent) == sorted(row["terminal_name"] for row in rows)
    assert not set(sent) & set(FAMILIES + GENERA)


def test_prefetch_fetches_the_rank_columns_of_a_row_whose_terminal_name_missed():
    rows = _lineage_rows(count=1)
    rows[0]["terminal_name"] = "Nomatch species"

    sent = _sent_by_prefetch(rows)

    assert sent[0] == "Nomatch species"
    assert set(sent[1:]) == {rows[0][f"source_{rank}"] for rank in RANKS_FROM_GENUS_UP}


def test_prefetch_skips_a_placeholder_rank_column_as_the_backoff_loop_does():
    rows = _lineage_rows(count=1)
    rows[0]["terminal_name"] = "Nomatch species"
    rows[0].update({f"source_{rank}": "" for rank in RANKS_FROM_GENUS_UP})
    rows[0]["source_genus"] = "incertae sedis"

    assert _sent_by_prefetch(rows) == ["Nomatch species"]


def test_prefetch_skips_the_rank_columns_of_a_compound_row_the_backoff_loop_never_reaches():
    rows = _lineage_rows(count=1)
    rows[0]["terminal_name"] = "Nomatch ocellata or erinacea"

    assert _sent_by_prefetch(rows) == ["Nomatch ocellata", "Nomatch erinacea"]


def test_prefetch_fetches_the_unranked_names_of_a_row_whose_terminal_name_missed():
    row = {
        "lineage_key": "k",
        "terminal_name": "MALV-II",
        "unranked_lineage": "Eukaryota;Alveolata;Dinoflagellata;core-syndiniales",
    }

    sent = _sent_by_prefetch([row])

    assert sent == ["MALV-II", "core-syndiniales", "Dinoflagellata", "Alveolata", "Eukaryota"]


def test_prefetch_fetches_the_rank_columns_of_a_row_whose_terminal_name_is_a_placeholder():
    rows = _lineage_rows(count=1)
    rows[0]["terminal_name"] = "Unassigned"

    sent = _sent_by_prefetch(rows)

    assert "Unassigned" not in sent
    assert set(sent) == {rows[0][f"source_{rank}"] for rank in RANKS_FROM_GENUS_UP}


@pytest.mark.parametrize("terminal_name", ["Nomatch{i}", "Unassigned"])
def test_prefetch_announces_every_request_it_is_about_to_make(capsys, monkeypatch, terminal_name):
    monkeypatch.delenv("EDNA2DWC_QUIET", raising=False)
    rows = _lineage_rows()
    for i, row in enumerate(rows):
        row["terminal_name"] = terminal_name.format(i=i)

    _prefetching_resolver().prefetch(rows)

    announced = sum(
        int(match.group(1).replace(",", ""))
        for match in re.finditer(r"-> ([\d,]+) requests", capsys.readouterr().err)
    )
    assert announced == api_usage.counts()["worms_match"]


def _run_step(tmp_path, handler, rows, *, output_name, refresh=False, **settings):
    output_path = tmp_path / output_name
    result = step(
        lineage_rows=rows,
        output_path=output_path,
        settings_by_scope={"": TaxonomySettings(**settings)},
        open_registers=registers_answering(handler, None if refresh else tmp_path / "cache"),
    )
    return output_path, result


@pytest.mark.parametrize("refresh", [False, True])
def test_the_resolve_taxonomy_step_prefetches_with_or_without_the_cache(
    tmp_path, monkeypatch, refresh
):
    rows = _lineage_rows()
    _run_step(
        tmp_path,
        _matches_terminal_names,
        rows,
        output_name="resolved_taxonomy.tsv",
        refresh=refresh,
        registers=("worms",),
    )

    assert api_usage.counts()["worms_match"] == _batches_for(rows)


GBIF_ONLY_SPECIES = _gbif_match(
    usageKey=5678,
    canonicalName="Gbifonly species",
    rank="SPECIES",
    kingdom="Animalia",
    genus="Gbifonly",
)
EVERY_RESOLUTION_PATH_RECORDS = {
    **LEUCORAJA_RECORDS,
    "Aaptos": [AAPTOS],
    "Suberitidae": [_record(AphiaID=132061, scientificname="Suberitidae", kingdom="Animalia")],
}


def _every_resolution_path_handler(request):
    url = str(request.url)
    if "AphiaRecordsByMatchNames" in url:
        return _worms_transport(EVERY_RESOLUTION_PATH_RECORDS)(request)
    if "AphiaRecordByAphiaID/132064" in url:
        return httpx.Response(200, json=AAPTOS)
    if "species/match" in url:
        if request.url.params.get("name") == "Gbifonly species":
            return httpx.Response(200, json=GBIF_ONLY_SPECIES)
        return httpx.Response(200, json={"matchType": "NONE", "synonym": False})
    if "dataset/" in url:
        return httpx.Response(200, json={"pubDate": "2026-01-01T00:00:00.000+0000"})
    return httpx.Response(404)


def _every_resolution_path_rows() -> list[dict[str, str]]:
    def row(key, terminal, **ranks):
        return {
            "lineage_key": key,
            "terminal_name": terminal,
            **{f"source_{rank}": ranks.get(rank, "") for rank in RANKS_FROM_GENUS_UP},
            "row_count": "1",
            "ncbi_taxid": ranks.get("ncbi_taxid", ""),
            "source_taxon_id": ranks.get("source_taxon_id", ""),
        }

    return [
        row("leaf", "Aaptos", kingdom="Animalia"),
        row("placeholder", "Unassigned", kingdom="Animalia", genus="Aaptos"),
        row("empty", "", kingdom="Animalia"),
        row("compound", "Leucoraja ocellata or erinacea", kingdom="Animalia"),
        row("backoff", "Nomatch species", kingdom="Animalia", family="Suberitidae"),
        row("gbif", "Gbifonly species", kingdom="Animalia"),
        row("unresolved", "Nomatch anywhere", kingdom="Animalia"),
        row("by_id", "Aaptos", source_taxon_id="urn:lsid:marinespecies.org:taxname:132064"),
        row("ncbi", "Aaptos", kingdom="Animalia", ncbi_taxid="9606"),
    ]


def test_prefetch_changes_no_resolution_path_finding_or_review_flag(tmp_path, monkeypatch):
    rows = _every_resolution_path_rows()

    def run(output_name: str):
        return _run_step(
            tmp_path,
            _every_resolution_path_handler,
            rows,
            output_name=output_name,
            registers=("worms", "gbif"),
        )

    prefetched_path, prefetched = run("with_prefetch.tsv")
    monkeypatch.setattr(TaxonResolver, "prefetch", lambda self, lineage_rows: None)
    plain_path, plain = run("without_prefetch.tsv")

    assert prefetched_path.read_bytes() == plain_path.read_bytes()
    assert prefetched.findings == plain.findings
    paths = {row["resolution_path"] for row in read_tab_separated_rows(prefetched_path)}
    assert paths == {
        "leaf",
        "incertae_sedis_placeholder",
        "compound_common_ancestor",
        "rank_backoff",
        "gbif_fallback",
        "biota_fallback",
    }


def _gadid_records() -> dict[str, list[dict]]:
    return {
        "Gadus morhua": [
            _record(
                AphiaID=126436,
                scientificname="Gadus morhua",
                kingdom="Animalia",
                family="Gadidae",
                genus="Gadus",
            )
        ],
        "Gadidae": [
            _record(
                AphiaID=125732,
                scientificname="Gadidae",
                rank="Family",
                kingdom="Animalia",
                family="Gadidae",
            )
        ],
        "Gadus": [
            _record(
                AphiaID=125732,
                scientificname="Gadus",
                rank="Genus",
                kingdom="Animalia",
                family="Gadidae",
                genus="Gadus",
            )
        ],
    }


def test_a_species_beside_its_family_is_published_at_the_family():
    resolver = _resolver(_gadid_records())
    result = resolver.resolve("Gadus morhua, other Gadidae", {"kingdom": "Animalia"})
    assert result.resolution_path == "compound_common_ancestor"
    assert result.scientific_name == "Gadidae"


def test_a_capitalized_compound_part_is_a_name_and_not_an_epithet_of_the_last_genus():
    sent: list[str] = []
    resolver = _rank_word_resolver(sent)
    resolver.resolve("Gadus morhua, other Gadidae", {})
    assert "Gadus Gadidae" not in sent


def test_a_register_candidate_named_for_a_rank_is_never_a_match():
    resolver = _resolver(
        {
            "Pseudocalanus moultoni": [
                _record(AphiaID=9, scientificname="Genus", rank="Genus", kingdom="Animalia")
            ],
            "Pseudocalanus": [
                _record(AphiaID=10, scientificname="Pseudocalanus", kingdom="Animalia")
            ],
        }
    )
    result = resolver.resolve(
        "Pseudocalanus moultoni", {"kingdom": "Animalia", "genus": "Pseudocalanus"}
    )
    assert result.scientific_name == "Pseudocalanus"
    assert "TAXON_FUZZY" not in result.findings


def test_a_resolver_refuses_non_confident_matches_unless_told_otherwise():
    assert TaxonResolver(WormsClient(client=httpx.Client()))._require_confident is True


def test_the_lock_names_each_lineages_source_beside_its_key(tmp_path):
    lineage_rows = [
        {
            "lineage_key": "k1",
            "terminal_name": "Aaptos",
            "source_kingdom": "Animalia",
            "source_phylum": "Porifera",
            "source_class": "",
            "source_order": "",
            "source_family": "",
            "source_genus": "Aaptos",
            "taxonomy_scope": "",
            "unranked_lineage": "",
        }
    ]
    resolved = ResolvedTaxon("k1", "Aaptos", "urn:lsid:1", "Genus", "", "accepted", "1", "")
    rows = resolve_taxonomy.lock_rows(lineage_rows, {"k1": resolved})
    assert list(rows[0])[:3] == ["lineage_key", "source_name", "source_lineage"]
    assert rows[0]["source_name"] == "Aaptos"
    assert rows[0]["source_lineage"] == "Animalia; Porifera; Aaptos"
