from __future__ import annotations

from edna2dwc.taxonomy.plausibility import (
    domains_implausible,
    has_organelle_marker,
    is_kingdom_uninformative,
    kingdom_group,
    kingdoms_implausible,
)


def test_kingdom_group_matches_case_insensitively():
    assert kingdom_group("bacteria") == "prokaryote"
    assert kingdom_group("BACTERIA") == "prokaryote"
    assert kingdom_group("Animalia") == "eukaryote_multicellular"
    assert kingdom_group("Stramenopiles") == "eukaryote_protist"
    assert kingdom_group("Viruses") == "virus"


def test_unmapped_kingdom_is_never_grounds_for_rejection():
    assert kingdom_group("Some Unknown Thing") is None
    assert kingdoms_implausible("Some Unknown Thing", "Animalia") is False
    assert kingdoms_implausible("Bacteria", "Some Unknown Thing") is False


def test_chloroplast_cyanobacteria_vs_plantae_is_implausible():
    assert kingdoms_implausible("Bacteria", "Plantae") is True


def test_stramenopile_vs_mollusc_is_implausible():
    assert kingdoms_implausible("Stramenopiles", "Animalia") is True


def test_same_group_is_plausible():
    assert kingdoms_implausible("Animalia", "Metazoa") is False


def test_eukaryote_any_wildcard_compatible_with_any_eukaryote_group():
    assert kingdoms_implausible("Eukaryota", "Animalia") is False
    assert kingdoms_implausible("Eukaryota", "Stramenopiles") is False
    assert kingdoms_implausible("Eukarya", "Fungi") is False


def test_eukaryote_any_wildcard_implausible_against_prokaryote_and_virus():
    assert kingdoms_implausible("Eukaryota", "Bacteria") is True
    assert kingdoms_implausible("Eukaryota", "Viruses") is True


def test_source_kingdom_uninformative_when_it_resolves_only_to_wildcard():
    assert is_kingdom_uninformative("Eukaryota") is True
    assert is_kingdom_uninformative("Eukarya") is True
    assert is_kingdom_uninformative("Animalia") is False
    assert is_kingdom_uninformative("") is False


def test_organelle_markers_matched_against_genus_family_order_class():
    assert has_organelle_marker("Chloroplast", "", "", "") is True
    assert has_organelle_marker("", "Mitochondria", "", "") is True
    assert has_organelle_marker("", "", "", "PLASTID") is True
    assert has_organelle_marker("Homo", "Hominidae", "Primates", "Mammalia") is False


def test_eukaryote_kingdoms_registers_disagree_on_share_a_domain():
    assert not domains_implausible("Plantae", "Chromista")
    assert not domains_implausible("Fungi", "Chromista")
    assert not domains_implausible("Eukaryota", "Animalia")


def test_a_prokaryote_and_a_eukaryote_are_different_domains():
    assert domains_implausible("Bacteria", "Plantae")
    assert domains_implausible("Animalia", "Archaea")
    assert domains_implausible("Viruses", "Bacteria")


def test_an_unmapped_kingdom_is_never_a_different_domain():
    assert not domains_implausible("", "Plantae")
    assert not domains_implausible("Some Unknown Thing", "Bacteria")
