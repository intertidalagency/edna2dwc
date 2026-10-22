from __future__ import annotations

import pytest

from edna2dwc.taxonomy.derive_lineage import (
    RANK_COLUMNS,
    derive_lineage,
    lineage_key,
    parse_taxonomy_string,
)
from tests.tables import dicts, table_of


def test_parses_the_d_prefix_grammar():
    parsed = parse_taxonomy_string("d__Bacteria;p__Cyanobacteria")
    assert parsed.ranks == {"kingdom": "Bacteria", "phylum": "Cyanobacteria"}
    assert parsed.terminal == "Cyanobacteria"


def test_bare_unassigned_is_read_whole_rather_than_truncated_into_a_taxon():
    parsed = parse_taxonomy_string("Unassigned")
    assert parsed.terminal == ""
    assert parsed.ranks == {}


def test_anchored_stripping_only_matches_real_rank_prefixes():
    parsed = parse_taxonomy_string("d__Bacteria;weird__thing")
    assert parsed.terminal == "weird__thing"
    assert parsed.ranks == {"kingdom": "Bacteria"}


def test_terminal_is_the_deepest_non_blank_token():
    parsed = parse_taxonomy_string("d__Bacteria;p__;c__;o__;f__;g__")
    assert parsed.terminal == "Bacteria"
    assert parsed.ranks == {"kingdom": "Bacteria"}


def test_lineage_key_is_stable_across_releases():
    ranks = {"kingdom": "Bacteria", "phylum": "Cyanobacteria"}
    assert lineage_key("Cyanobacteria", ranks) == "154297d9d3747001"


def test_derive_lineage_dedupes_identical_tuples_and_counts_rows():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "taxonomy": "d__Bacteria;p__Cyanobacteria",
        },
        {
            "sampleID": "S2",
            "featureID": "f2",
            "count": "1",
            "taxonomy": "d__Bacteria;p__Cyanobacteria",
        },
        {
            "sampleID": "S3",
            "featureID": "f3",
            "count": "1",
            "taxonomy": "d__Bacteria;p__Firmicutes",
        },
    ]
    result = derive_lineage(table_of(rows))
    assert len(result.lineage_rows) == 2
    by_terminal = {r["terminal_name"]: r for r in result.lineage_rows}
    assert by_terminal["Cyanobacteria"]["row_count"] == "2"
    assert by_terminal["Firmicutes"]["row_count"] == "1"
    assert all("lineage_key" in row for row in dicts(result.occurrences))


def test_placeholder_terminal_does_not_collapse_distinct_lineages():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "taxonomy": "d__Bacteria;p__Cyanobacteria;s__",
        },
        {
            "sampleID": "S2",
            "featureID": "f2",
            "count": "1",
            "taxonomy": "d__Bacteria;p__Firmicutes;s__",
        },
    ]
    result = derive_lineage(table_of(rows))
    assert len(result.lineage_rows) == 2
    assert len({r["lineage_key"] for r in result.lineage_rows}) == 2


def test_already_split_rank_columns_phyloseq_style():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "Kingdom": "Bacteria",
            "Phylum": "Cyanobacteria",
        }
    ]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Cyanobacteria"
    assert result.lineage_rows[0]["source_phylum"] == "Cyanobacteria"


def test_bare_scientific_name_with_no_rank_structure_at_all():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "1", "scientificName": "Acartia tonsa"}]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Acartia tonsa"
    assert all(result.lineage_rows[0][f"source_{r}"] == "" for r in RANK_COLUMNS)


def test_ncbi_taxid_and_source_taxon_id_carried_onto_lineage_row_when_present():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "taxonomy": "d__Bacteria",
            "ncbi_taxid": "1224",
            "source_taxon_id": "urn:lsid:marinespecies.org:taxname:2",
        }
    ]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["ncbi_taxid"] == "1224"
    assert result.lineage_rows[0]["source_taxon_id"] == "urn:lsid:marinespecies.org:taxname:2"


def test_rows_that_share_a_lineage_but_not_their_taxon_ids_are_resolved_apart():
    rows = [
        {"featureID": "f1", "taxonomy": "g__Aaptos", "ncbi_taxid": "6544"},
        {"featureID": "f2", "taxonomy": "g__Aaptos", "ncbi_taxid": "6545"},
        {"featureID": "f3", "taxonomy": "g__Aaptos", "source_taxon_id": "132064"},
        {"featureID": "f4", "taxonomy": "g__Aaptos"},
    ]
    result = derive_lineage(table_of(rows))
    assert len({row["lineage_key"] for row in dicts(result.occurrences)}) == 4
    assert sorted((row["ncbi_taxid"], row["source_taxon_id"]) for row in result.lineage_rows) == [
        ("", ""),
        ("", "132064"),
        ("6544", ""),
        ("6545", ""),
    ]


def test_a_lineage_with_no_taxon_ids_keeps_the_key_it_had():
    rows = [{"featureID": "f1", "taxonomy": "d__Bacteria;p__Cyanobacteria"}]
    assert derive_lineage(table_of(rows)).lineage_rows[0]["lineage_key"] == "154297d9d3747001"


def test_a_marker_with_its_own_taxonomy_settings_resolves_its_lineages_apart():
    rows = [
        {"featureID": "f1", "marker": "16S", "taxonomy": "d__Bacteria"},
        {"featureID": "f2", "marker": "18S", "taxonomy": "d__Bacteria"},
        {"featureID": "f3", "marker": "COI", "taxonomy": "d__Bacteria"},
    ]
    result = derive_lineage(table_of(rows), scopes={"16S": "16S"})
    scopes = {row["featureID"]: row["lineage_key"] for row in dicts(result.occurrences)}
    assert scopes["f2"] == scopes["f3"] != scopes["f1"]
    assert sorted(row["taxonomy_scope"] for row in result.lineage_rows) == ["", "16S"]


def _rank_column_row(**columns: str) -> dict[str, str]:
    return {"sampleID": "S1", "featureID": "f1", "count": "1", **columns}


def test_species_column_becomes_the_terminal_name():
    rows = [_rank_column_row(kingdom="Animalia", genus="Acartia", species="Acartia tonsa")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Acartia tonsa"
    assert result.lineage_rows[0]["source_genus"] == "Acartia"


def test_bare_epithet_is_joined_to_the_genus_column():
    rows = [_rank_column_row(genus="Acartia", species="tonsa")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Acartia tonsa"


def test_species_column_repeating_the_genus_is_not_doubled():
    rows = [_rank_column_row(genus="Acartia", species="Acartia")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Acartia"


def test_species_column_is_read_case_insensitively():
    rows = [_rank_column_row(Genus="Acartia", Species="tonsa")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Acartia tonsa"


def test_epithet_with_no_genus_column_stands_alone():
    rows = [_rank_column_row(family="Acartiidae", species="tonsa")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "tonsa"


def test_scientific_name_column_outranks_the_genus_capped_rank_walk():
    rows = [_rank_column_row(kingdom="Animalia", genus="Acartia", scientificName="Acartia tonsa")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Acartia tonsa"


def test_lowercase_scientific_name_column_is_read_too():
    rows = [_rank_column_row(kingdom="Animalia", genus="Acartia", scientificname="Acartia tonsa")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Acartia tonsa"


def test_lowercase_verbatim_identification_is_the_last_resort():
    rows = [_rank_column_row(verbatimidentification="Acartia tonsa")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Acartia tonsa"


def test_rank_walk_outranks_verbatim_identification():
    rows = [
        _rank_column_row(kingdom="Animalia", verbatimIdentification="d__Animalia;p__Arthropoda")
    ]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Animalia"


def test_a_sentinel_rank_value_is_not_part_of_the_lineage():
    rows = [_rank_column_row(kingdom="Animalia", phylum="Annelida", **{"class": "NA"})]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["source_class"] == ""
    assert result.lineage_rows[0]["terminal_name"] == "Annelida"


def test_a_sentinel_scientific_name_leaves_the_rank_walk_to_name_the_lineage():
    rows = [_rank_column_row(kingdom="Animalia", scientificName="unassigned")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Animalia"


def test_a_row_of_nothing_but_sentinels_has_no_terminal_name():
    rows = [_rank_column_row(kingdom="NA", phylum="N/A", scientificName="Unassigned")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == ""
    assert all(result.lineage_rows[0][f"source_{r}"] == "" for r in RANK_COLUMNS)


def test_a_sentinel_epithet_is_never_joined_onto_its_genus():
    rows = [_rank_column_row(genus="Acartia", species="NA")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Acartia"


def test_a_sentinel_taxonomy_token_is_skipped():
    rows = [_rank_column_row(taxonomy="d__Bacteria;p__unclassified")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Bacteria"
    assert result.lineage_rows[0]["source_phylum"] == ""


def test_the_occurrence_row_keeps_the_sentinel_out_of_its_taxon_columns():
    rows = [_rank_column_row(kingdom="Animalia", scientificName="NA", **{"class": "NA"})]
    result = derive_lineage(table_of(rows))
    row = dicts(result.occurrences)[0]
    assert row["class"] == ""
    assert row["scientificName"] == ""
    assert row["kingdom"] == "Animalia"


def test_the_original_sentinel_string_survives_in_verbatim_identification():
    rows = [_rank_column_row(kingdom="NA", scientificName="incertae sedis")]
    result = derive_lineage(table_of(rows))
    assert dicts(result.occurrences)[0]["verbatimIdentification"] == "incertae sedis"


def test_a_sentinel_species_beside_a_real_rank_is_not_kept_as_the_identification():
    rows = [
        _rank_column_row(
            family="Flavobacteriaceae", genus="Flavobacterium", species="uncultured_marine"
        )
    ]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Flavobacterium"
    assert "verbatimIdentification" not in dicts(result.occurrences)[0]


def test_a_real_verbatim_identification_is_never_overwritten_by_a_sentinel():
    rows = [
        _rank_column_row(scientificName="Unassigned", verbatimIdentification="d__Bacteria;p__NA")
    ]
    result = derive_lineage(table_of(rows))
    assert dicts(result.occurrences)[0]["verbatimIdentification"] == "d__Bacteria;p__NA"


def test_a_source_scientific_name_is_kept_as_the_verbatim_identification():
    rows = [_rank_column_row(kingdom="Animalia", scientificName="Acartia tonsa Dana, 1849")]
    result = derive_lineage(table_of(rows))
    assert dicts(result.occurrences)[0]["verbatimIdentification"] == "Acartia tonsa Dana, 1849"


def test_a_source_scientific_name_never_replaces_a_source_verbatim_identification():
    rows = [_rank_column_row(scientificName="Acartia tonsa", verbatimIdentification="Acartia sp.")]
    result = derive_lineage(table_of(rows))
    assert dicts(result.occurrences)[0]["verbatimIdentification"] == "Acartia sp."


def test_a_sentinel_species_does_not_hide_a_real_scientific_name():
    rows = [_rank_column_row(genus="Acartia", species="NA", scientificName="Acartia tonsa")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == "Acartia tonsa"
    assert dicts(result.occurrences)[0]["verbatimIdentification"] == "Acartia tonsa"


def test_a_taxonomy_string_that_is_nothing_but_sentinels_survives_in_verbatim_identification():
    rows = [_rank_column_row(taxonomy="d__NA;p__unclassified")]
    result = derive_lineage(table_of(rows))
    assert result.lineage_rows[0]["terminal_name"] == ""
    assert dicts(result.occurrences)[0]["verbatimIdentification"] == "d__NA;p__unclassified"


def test_an_empty_species_token_alone_is_not_recorded_as_a_sentinel():
    rows = [_rank_column_row(taxonomy="s__")]
    result = derive_lineage(table_of(rows))
    assert "verbatimIdentification" not in dicts(result.occurrences)[0]


MICROMONAS_RANKS = {
    "kingdom": "Eukaryota",
    "phylum": "Chlorophyta",
    "class": "Mamiellophyceae",
    "order": "Mamiellales",
    "family": "Mamiellaceae",
    "genus": "Micromonas",
}


@pytest.mark.parametrize(
    "lineage",
    [
        (
            "Kingdom: Eukaryota | Phylum: Chlorophyta | Class: Mamiellophyceae | "
            "Order: Mamiellales | Family: Mamiellaceae | Genus: Micromonas | "
            "Species: Micromonas pusilla"
        ),
        (
            "kingdom:Eukaryota;phylum:Chlorophyta;class:Mamiellophyceae;order:Mamiellales;"
            "family:Mamiellaceae;genus:Micromonas;species:Micromonas pusilla"
        ),
        (
            "KINGDOM: Eukaryota|PHYLUM: Chlorophyta|CLASS: Mamiellophyceae|ORDER: Mamiellales|"
            "FAMILY: Mamiellaceae|GENUS: Micromonas|SPECIES: Micromonas pusilla|"
        ),
    ],
)
def test_a_labelled_lineage_fills_each_rank_its_label_names(lineage):
    parsed = parse_taxonomy_string(lineage)
    assert parsed.ranks == MICROMONAS_RANKS
    assert parsed.terminal == "Micromonas pusilla"


def test_a_labelled_lineage_skips_blank_names():
    parsed = parse_taxonomy_string(
        "Kingdom: Eukaryota | Phylum: Cnidaria | Class: Anthozoa | Order: Actiniaria | "
        "Family:  | Genus:  | Species: "
    )
    assert parsed.ranks == {
        "kingdom": "Eukaryota",
        "phylum": "Cnidaria",
        "class": "Anthozoa",
        "order": "Actiniaria",
    }
    assert parsed.terminal == "Actiniaria"


@pytest.mark.parametrize("placeholder", ["order_Orbiniidae", "Order_Orbiniidae", "phylum_X"])
def test_a_labelled_lineage_reads_a_rank_word_placeholder_as_blank(placeholder):
    parsed = parse_taxonomy_string(
        f"Kingdom: Eukaryota | Phylum: Annelida | Order: {placeholder} | Family: Orbiniidae | "
        "Genus: Naineris | Species: Naineris dendritica CMC01"
    )
    assert "order" not in parsed.ranks
    assert parsed.ranks["family"] == "Orbiniidae"
    assert parsed.terminal == "Naineris dendritica CMC01"


def test_a_labelled_lineage_maps_domain_and_division_onto_the_rank_columns():
    parsed = parse_taxonomy_string("Domain: Eukaryota | Division: Rhodophyta | Genus: Mazzaella")
    assert parsed.ranks == {"kingdom": "Eukaryota", "phylum": "Rhodophyta", "genus": "Mazzaella"}
    assert parsed.terminal == "Mazzaella"


def test_a_labelled_lineage_keeps_an_unmapped_rank_out_of_the_rank_columns():
    parsed = parse_taxonomy_string("Kingdom: Animalia | Subclass: Copepoda")
    assert parsed.ranks == {"kingdom": "Animalia"}
    assert parsed.terminal == "Copepoda"


def test_a_labelled_sentinel_is_read_as_empty():
    parsed = parse_taxonomy_string("Kingdom: Eukaryota | Phylum: unassigned | Species: ")
    assert parsed.ranks == {"kingdom": "Eukaryota"}
    assert parsed.terminal == "Eukaryota"


def test_an_unlabelled_lineage_keeps_a_colon_inside_a_name():
    parsed = parse_taxonomy_string("Bacteria;Proteobacteria;Clade: SAR11")
    assert parsed.ranks == {}
    assert parsed.terminal == "Clade: SAR11"


def test_an_unlabelled_pipe_lineage_separates_ranks_like_a_semicolon():
    parsed = parse_taxonomy_string("Eukaryota | Chordata | Gadidae | Gadus")
    assert parsed.terminal == "Gadus"
    assert parsed.ranks == {}
    assert parsed.unranked == ("Eukaryota", "Chordata", "Gadidae")


COPEPOD_LINEAGE = (
    "Eukaryota|Amorphea|Obazoa|Opisthokonta|Holozoa|Choanozoa|Metazoa|Animalia|parahoxozoa|"
    "Bilateria|Protostomia|Ecdysozoa|Panarthropoda|Arthropoda|Mandibulata|Pancrustacea|Copepoda"
)
COPEPOD_LINEAGE_NAMES = (
    "Eukaryota",
    "Amorphea",
    "Obazoa",
    "Opisthokonta",
    "Holozoa",
    "Choanozoa",
    "Metazoa",
    "Animalia",
    "parahoxozoa",
    "Bilateria",
    "Protostomia",
    "Ecdysozoa",
    "Panarthropoda",
    "Arthropoda",
    "Mandibulata",
    "Pancrustacea",
    "Copepoda",
)


@pytest.mark.parametrize(
    ("lineage", "ranks", "terminal", "unranked"),
    [
        (
            f"{COPEPOD_LINEAGE}|Calanoida|megacalanoids|Calanidae|*|*|*",
            {},
            "Calanidae",
            (*COPEPOD_LINEAGE_NAMES, "Calanoida", "megacalanoids"),
        ),
        (
            (
                f"{COPEPOD_LINEAGE}|Podoplea|Cyclopoida|Oithonida|core-O|CO-clade|Oithonidae|"
                "g:Dioithona|isolate=1-New-Caledonia-RJH-2001"
            ),
            {},
            "Dioithona",
            (
                *COPEPOD_LINEAGE_NAMES,
                "Podoplea",
                "Cyclopoida",
                "Oithonida",
                "core-O",
                "CO-clade",
                "Oithonidae",
            ),
        ),
        (
            (
                f"{COPEPOD_LINEAGE}|Calanoida|clausocalanoids|ACE-clade|Clausocalanidae|"
                "g:Pseudocalanus|Pseudocalanus+moultoni|isolate=MT00778"
            ),
            {},
            "Pseudocalanus moultoni",
            (
                *COPEPOD_LINEAGE_NAMES,
                "Calanoida",
                "clausocalanoids",
                "ACE-clade",
                "Clausocalanidae",
                "Pseudocalanus",
            ),
        ),
        (
            "Eukaryota|Diaphoretickes|Sar|Alveolata|Myzozoa|DP-clade|Dinoflagellata|Dinophyceae|*|*",
            {},
            "Dinophyceae",
            (
                "Eukaryota",
                "Diaphoretickes",
                "Sar",
                "Alveolata",
                "Myzozoa",
                "DP-clade",
                "Dinoflagellata",
            ),
        ),
        (
            (
                "Bacteria;Proteobacteria;Gammaproteobacteria;Steroidobacterales;Woeseiaceae;Woeseia;"
                "uncultured_marine"
            ),
            {},
            "Woeseia",
            (
                "Bacteria",
                "Proteobacteria",
                "Gammaproteobacteria",
                "Steroidobacterales",
                "Woeseiaceae",
            ),
        ),
        (
            (
                "d__Bacteria;p__Cyanobacteria;c__Cyanobacteriia;o__Synechococcales;f__Cyanobiaceae;"
                "g__Cyanobium_PCC-6307;s__NA"
            ),
            {
                "kingdom": "Bacteria",
                "phylum": "Cyanobacteria",
                "class": "Cyanobacteriia",
                "order": "Synechococcales",
                "family": "Cyanobiaceae",
                "genus": "Cyanobium_PCC-6307",
            },
            "Cyanobium_PCC-6307",
            (),
        ),
        (
            (
                "Eukaryota;Haptista;Haptophyta;Haptophyta_X;Prymnesiophyceae;Prymnesiales;"
                "Chrysochromulinaceae;Chrysochromulina;Chrysochromulina_sp."
            ),
            {},
            "Chrysochromulina_sp.",
            (
                "Eukaryota",
                "Haptista",
                "Haptophyta",
                "Haptophyta_X",
                "Prymnesiophyceae",
                "Prymnesiales",
                "Chrysochromulinaceae",
                "Chrysochromulina",
            ),
        ),
        (
            "Eukaryota;TSAR;Stramenopiles;Gyrista;Gyrista_X;Gyrista_XX;MAST-2;MAST-2B;MAST-2B_sp.",
            {},
            "MAST-2B_sp.",
            (
                "Eukaryota",
                "TSAR",
                "Stramenopiles",
                "Gyrista",
                "Gyrista_X",
                "Gyrista_XX",
                "MAST-2",
                "MAST-2B",
            ),
        ),
        (
            "Kingdom: Eukaryota | Phylum: unknown | Class: Dinophyceae",
            {"kingdom": "Eukaryota", "class": "Dinophyceae"},
            "Dinophyceae",
            (),
        ),
    ],
)
def test_a_real_lineage_string_parses_as_the_source_meant_it(lineage, ranks, terminal, unranked):
    parsed = parse_taxonomy_string(lineage)
    assert (parsed.ranks, parsed.terminal, parsed.unranked) == (ranks, terminal, unranked)


@pytest.mark.parametrize(
    ("columns", "terminal", "ranks"),
    [
        (
            {
                "Kingdom": "Eukaryota",
                "Phylum": "Arthropoda",
                "Class": "Hexanauplia",
                "Order": "Calanoida",
                "Family": "Paracalanidae",
                "Genus": "Paracalanus",
                "Species": "unassigned",
            },
            "Paracalanus",
            {
                "kingdom": "Eukaryota",
                "phylum": "Arthropoda",
                "class": "Hexanauplia",
                "order": "Calanoida",
                "family": "Paracalanidae",
                "genus": "Paracalanus",
            },
        ),
        (
            {
                "Kingdom": "Eukaryota",
                "Phylum": "unknown",
                "Class": "Dinophyceae",
                "Order": "Gymnodiniales",
                "Family": "Gymnodiniaceae",
                "Genus": "Akashiwo",
                "Species": "Akashiwo sanguinea",
            },
            "Akashiwo sanguinea",
            {
                "kingdom": "Eukaryota",
                "class": "Dinophyceae",
                "order": "Gymnodiniales",
                "family": "Gymnodiniaceae",
                "genus": "Akashiwo",
            },
        ),
        (
            {
                "kingdom": "Bacteria",
                "phylum": "Actinobacteriota",
                "class": "Acidimicrobiia",
                "order": "Microtrichales",
                "family": "Microtrichaceae",
                "genus": "Sva0996_marine_group",
                "species": "",
            },
            "Sva0996_marine_group",
            {
                "kingdom": "Bacteria",
                "phylum": "Actinobacteriota",
                "class": "Acidimicrobiia",
                "order": "Microtrichales",
                "family": "Microtrichaceae",
                "genus": "Sva0996_marine_group",
            },
        ),
        (
            {
                "Kingdom": "Eukaryota",
                "Phylum": "Annelida",
                "Class": "Polychaeta",
                "Order": "Eunicida",
                "Family": "Lumbrineridae",
                "Genus": "no identification",
                "Species": "no identification",
            },
            "Lumbrineridae",
            {
                "kingdom": "Eukaryota",
                "phylum": "Annelida",
                "class": "Polychaeta",
                "order": "Eunicida",
                "family": "Lumbrineridae",
            },
        ),
        (
            {
                "Kingdom": "Bacteria",
                "Phylum": "Proteobacteria",
                "Class": "Gammaproteobacteria",
                "Order": "HOC36",
                "Family": "HOC36",
                "Genus": "HOC36",
                "Species": "Candidatus_Thioglobus",
            },
            "Candidatus_Thioglobus",
            {
                "kingdom": "Bacteria",
                "phylum": "Proteobacteria",
                "class": "Gammaproteobacteria",
                "order": "HOC36",
                "family": "HOC36",
                "genus": "HOC36",
            },
        ),
        ({"scientificname": "incertae sedis"}, "", {}),
        (
            {"scientificName": "Merluccius productus", "Class": "Actinopteri"},
            "Merluccius productus",
            {"class": "Actinopteri"},
        ),
    ],
)
def test_real_rank_columns_name_the_lineage_the_source_meant(columns, terminal, ranks):
    rows = [{"featureID": "f1", **columns}]
    lineage = derive_lineage(table_of(rows)).lineage_rows[0]
    assert lineage["terminal_name"] == terminal
    assert {
        rank: lineage[f"source_{rank}"] for rank in RANK_COLUMNS if lineage[f"source_{rank}"]
    } == ranks


CYANOBIUM = (
    "Bacteria; Cyanobacteria; Cyanobiia; Synechococcales; Prochlorococcaceae; Cyanobium_PCC-6307"
)


def test_an_unranked_lineage_keeps_every_name_above_its_terminal():
    parsed = parse_taxonomy_string(CYANOBIUM)
    assert parsed.ranks == {}
    assert parsed.terminal == "Cyanobium_PCC-6307"
    assert parsed.unranked == (
        "Bacteria",
        "Cyanobacteria",
        "Cyanobiia",
        "Synechococcales",
        "Prochlorococcaceae",
    )


def test_an_unranked_lineage_skips_its_sentinels():
    parsed = parse_taxonomy_string("Eukaryota;unclassified;Dinoflagellata;NA;MALV-II")
    assert parsed.unranked == ("Eukaryota", "Dinoflagellata")
    assert parsed.terminal == "MALV-II"


def test_a_ranked_lineage_has_no_unranked_names():
    assert parse_taxonomy_string("d__Bacteria;p__Cyanobacteria;weird").unranked == ()


def test_the_unranked_names_reach_the_lineage_row():
    rows = [{"featureID": "f1", "taxonomy": CYANOBIUM}]
    lineage = derive_lineage(table_of(rows)).lineage_rows[0]
    assert lineage["unranked_lineage"] == (
        "Bacteria;Cyanobacteria;Cyanobiia;Synechococcales;Prochlorococcaceae"
    )
    assert all(lineage[f"source_{rank}"] == "" for rank in RANK_COLUMNS)


def test_unranked_lineages_sharing_a_terminal_name_are_resolved_apart():
    rows = [
        {"featureID": "f1", "taxonomy": "Bacteria;Proteobacteria;Clade_Ia"},
        {"featureID": "f2", "taxonomy": "Bacteria;Bacteroidota;Clade_Ia"},
    ]
    result = derive_lineage(table_of(rows))
    assert len({row["lineage_key"] for row in result.lineage_rows}) == 2


def test_a_one_name_lineage_keeps_the_key_it_had():
    rows = [{"featureID": "f1", "taxonomy": "Acartia tonsa", "ncbi_taxid": "6935"}]
    lineage = derive_lineage(table_of(rows)).lineage_rows[0]
    assert lineage["lineage_key"] == lineage_key("Acartia tonsa", {}, "6935", "", "")


def test_rank_columns_outrank_an_unranked_taxonomy_string():
    rows = [
        _rank_column_row(
            taxonomy="Eukaryota;Alveolata;Dinoflagellata;Gymnodiniales",
            kingdom="Eukaryota",
            phylum="Dinoflagellata",
            order="Gymnodiniales",
        )
    ]
    lineage = derive_lineage(table_of(rows)).lineage_rows[0]
    assert lineage["source_phylum"] == "Dinoflagellata"
    assert lineage["source_order"] == "Gymnodiniales"
    assert lineage["terminal_name"] == "Gymnodiniales"
    assert lineage["unranked_lineage"] == ""


def test_a_ranked_taxonomy_string_still_outranks_rank_columns():
    rows = [_rank_column_row(taxonomy="d__Bacteria;p__Cyanobacteria", kingdom="Animalia")]
    lineage = derive_lineage(table_of(rows)).lineage_rows[0]
    assert lineage["source_kingdom"] == "Bacteria"
    assert lineage["terminal_name"] == "Cyanobacteria"
