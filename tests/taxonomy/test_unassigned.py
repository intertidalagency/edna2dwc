import pytest

from edna2dwc.taxonomy import unassigned


@pytest.mark.parametrize(
    "name", ["Biota incertae sedis", "Biota", "biota incertae sedis", "  Biota  "]
)
def test_placeholder_taxa_are_recognized_however_they_are_cased_or_padded(name):
    assert unassigned.is_placeholder_taxon(name)


@pytest.mark.parametrize("name", ["Animalia", "Chromista", "Plantae", "Biota incertae", "", "   "])
def test_a_real_kingdom_and_an_empty_cell_are_not_placeholder_taxa(name):
    assert not unassigned.is_placeholder_taxon(name)


@pytest.mark.parametrize(
    "value",
    [
        "NA",
        "na",
        "N/A",
        " n/a ",
        "none",
        "None",
        "root",
        "cellular organisms",
        "unassigned",
        "Unassigned",
        "unclassified",
        "no hit",
        "no_hit",
        "unknown",
        "uncultured",
        "incertae sedis",
        "Incertae Sedis",
        "unassigned_Bacteria",
        "marine metagenome",
        "seawater_metagenome",
        "metagenome",
        "uncultured_Flavobacteriia",
        "uncultured bacterium",
        "unidentified_marine",
        "unclassified_Bacteria",
        "unknown genus",
        "Unknown_Family",
        "unknown domain",
        "no identification",
        "no_identification",
        "nohit",
    ],
)
def test_every_spelling_of_no_assignment_is_recognized(value):
    assert unassigned.is_no_assignment(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "Animalia",
        "Nannochloropsis",
        "Naididae",
        "Rootia",
        "Nassarius",
        "Noctiluca",
        "Unculturedia",
        "Unknowna",
        "Nohitia",
        "Unknownia",
        "Metagenomia",
    ],
)
def test_a_real_name_and_an_empty_cell_are_not_a_no_assignment_sentinel(value):
    assert not unassigned.is_no_assignment(value)
