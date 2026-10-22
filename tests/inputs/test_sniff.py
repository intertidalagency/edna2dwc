from pathlib import Path

import pytest

from edna2dwc.inputs.sniff import data_suffix, looks_delimited

TITLED_TABLE = "Exported from LIMS 2024-05-01\nsampleID\tfeatureID\tcount\n" + "".join(
    f"s{i}\tf{i}\t{i}\n" for i in range(10)
)


@pytest.mark.parametrize(
    "text",
    [
        "sampleID\tfeatureID\ns1\tf1\n",
        "sample_id;feature_id;reads\nSAMP-01;ASV001;42\n",
        "sampleID\tfeatureID\ns1\tf1\ns2",
        TITLED_TABLE,
        'sampleID,notes\ns1,"filtered, then extracted"\ns2,plain\n',
    ],
)
def test_looks_delimited_accepts_a_table(text):
    assert looks_delimited(text)


@pytest.mark.parametrize(
    "text",
    [
        (
            "Methods\n\nWater samples were filtered, then extracted.\n"
            "Primers: mlCOIintF / jgHCO2198. Annealing at 46 C, 35 cycles.\n"
        ),
        (
            "Water was collected at each station, filtered on site, and frozen.\n"
            "Extraction followed the manufacturer protocol.\n"
            "Libraries were sequenced on a MiSeq, 2x300 bp, at the core facility.\n"
            "Reads were denoised with DADA2.\n"
        ),
        "onlyonecolumn\nvalue\n",
        "",
    ],
)
def test_looks_delimited_rejects_prose(text):
    assert not looks_delimited(text)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("counts.csv.gz", ".csv"),
        ("counts.TSV.GZ", ".tsv"),
        ("table.biom.gz", ".gz"),
        ("a.csv", ".csv"),
    ],
)
def test_data_suffix_looks_through_gz_only_on_a_delimited_file(name, expected):
    assert data_suffix(Path(name)) == expected
