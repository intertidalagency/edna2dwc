from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "occurrence_long"

_VALID_HEADER = "sampleID\tfeatureID\tcount\ttaxonomy\n"
_VALID_ROWS = (
    "s1\tf1\t10\td__Bacteria;p__Cyanobacteria\n"
    "s1\tf2\t5\td__Bacteria;p__Firmicutes\n"
    "s2\tf1\t20\td__Bacteria;p__Cyanobacteria\n"
)

FIXTURES: list[tuple[str, str, list[str]]] = [
    ("00_valid.tsv", _VALID_HEADER + _VALID_ROWS, []),
    (
        "00_valid_rank_columns.tsv",
        "sampleID\tfeatureID\tcount\tKingdom\tPhylum\ns1\tf1\t10\tBacteria\tCyanobacteria\n",
        [],
    ),
    (
        "01_missing_sampleid.tsv",
        "featureID\tcount\ttaxonomy\nf1\t10\td__Bacteria\n",
        ["CONTRACT_COLUMN_MISSING"],
    ),
    (
        "02_missing_count.tsv",
        "sampleID\tfeatureID\ttaxonomy\ns1\tf1\td__Bacteria\n",
        ["CONTRACT_COLUMN_MISSING"],
    ),
    (
        "03_count_is_na.tsv",
        _VALID_HEADER + "s1\tf1\tNA\td__Bacteria\n",
        ["CONTRACT_TYPE_INVALID"],
    ),
    (
        "04_negative_count.tsv",
        _VALID_HEADER + "s1\tf1\t-5\td__Bacteria\n",
        ["CONTRACT_TYPE_INVALID"],
    ),
    (
        "05_empty_featureid.tsv",
        _VALID_HEADER + "s1\t\t10\td__Bacteria\n",
        ["CONTRACT_INVALID"],
    ),
    (
        "06_embedded_tab.tsv",
        'sampleID\tfeatureID\tcount\ttaxonomy\tnotes\ns1\tf1\t10\td__Bacteria\t"bad\tvalue"\n',
        ["CONTRACT_INVALID"],
    ),
    (
        "07_no_taxonomy_or_rank.tsv",
        "sampleID\tfeatureID\tcount\ns1\tf1\t10\n",
        ["CONTRACT_COLUMN_MISSING"],
    ),
    (
        "08_duplicate_sample_feature_pair.tsv",
        _VALID_HEADER + "s1\tf1\t10\td__Bacteria\ns1\tf1\t20\td__Bacteria\n",
        ["CONTRACT_INVALID"],
    ),
    (
        "sampleID\tfeatureID\tcount\tcount\ns1\tf1\t10\t10\n",
        ["CONTRACT_INVALID"],
    ),
]


def write_fixtures(root: Path = FIXTURES_DIR) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, content, _codes in FIXTURES:
        path = root / filename
        path.write_text(content)
        written.append(path)
    return written


if __name__ == "__main__":
    paths = write_fixtures()
    print(f"Wrote {len(paths)} fixture(s) to {FIXTURES_DIR}")
