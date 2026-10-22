from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil

import yaml

from tests.make_golden_archives import GOLDEN_DIR

CASE = GOLDEN_DIR / "two_markers"
PRIMERS = {
    "Leray-COI": "COI\tmlCOIintF\tGGWACWGGWTGAACWGTWTAYCCYCC\tjgHCO2198\tTAIACYTCIGGRTGICCRAARAAYCA",
    "MiFish-U": "12S rRNA\tMiFish-U-F\tGTCGGTAAAACTCGTGCCAGC\tMiFish-U-R\tCATAGTGGGGTATCTAATCCCAGTTTG",
}
LINEAGES = [
    (
        "Leray-COI",
        "d__Eukaryota;p__Mollusca;c__Bivalvia;o__Mytilida;f__Mytilidae;g__Mytilus;s__Mytilus trossulus",
    ),
    (
        "Leray-COI",
        "d__Eukaryota;p__Arthropoda;c__Hexanauplia;o__Calanoida;f__Calanidae;g__Calanus;s__Calanus pacificus",
    ),
    (
        "Leray-COI",
        "d__Eukaryota;p__Echinodermata;c__Asteroidea;o__Forcipulatida;f__Asteriidae;g__Pisaster",
    ),
    (
        "MiFish-U",
        "d__Eukaryota;p__Chordata;c__Actinopteri;o__Clupeiformes;f__Clupeidae;g__Clupea;s__Clupea pallasii",
    ),
    (
        "MiFish-U",
        "d__Eukaryota;p__Chordata;c__Actinopteri;o__Salmoniformes;f__Salmonidae;g__Oncorhynchus;s__Oncorhynchus keta",
    ),
    (
        "MiFish-U",
        "d__Eukaryota;p__Chordata;c__Mammalia;o__Primates;f__Hominidae;g__Homo;s__Homo sapiens",
    ),
    ("MiFish-U", "Unassigned"),
]
BASES = "ACGT"
SAMPLES = 500


def _sequence(n: int) -> str:
    return "".join(BASES[(n >> (2 * i)) & 3] for i in range(30))


def _source_dynamic_properties(sample: int) -> str:
    if sample % 3:
        return ""
    readings = {f"ctd_{k}": round(sample * (k + 1) % 499 / 3, 2) for k in range(10)}
    remarks = {f"remark_{k}": f"bottle {k} at station {sample % 37}" for k in range(10)}
    return json.dumps({**readings, **remarks})


def _count(feature: int, sample: int) -> int:
    return 1 + feature * SAMPLES + sample


@dataclass(frozen=True)
class Shape:
    measurements: int = 0
    notes: int = 0
    wide_counts: bool = False
    source_dynamic_properties: bool = False
    controls_typed: bool = False
    every_row_corrected: bool = False


NARROW = Shape()
WIDE = Shape(
    measurements=27,
    notes=50,
    wide_counts=True,
    source_dynamic_properties=True,
    controls_typed=True,
    every_row_corrected=True,
)
CONTROL_EVERY = 50


def write_conversion(directory: Path, rows: int, shape: Shape = NARROW) -> None:
    features = rows // SAMPLES
    tables = directory / "tables"
    tables.mkdir(parents=True)
    with (tables / "features.tsv").open("w", encoding="utf-8") as out:
        out.write(
            "featureID\tmarker\tsequence\ttaxonomy\ttarget_gene\tpcr_primer_name_forward"
            "\tpcr_primer_forward\tpcr_primer_name_reverse\tpcr_primer_reverse\n"
        )
        for f in range(features):
            marker, taxonomy = LINEAGES[f % len(LINEAGES)]
            out.write(f"asv{f}\t{marker}\t{_sequence(f)}\t{taxonomy}\t{PRIMERS[marker]}\n")
    extra = [f"reading_{m}" for m in range(shape.measurements)] + [
        f"note_{n}" for n in range(shape.notes)
    ]
    if shape.source_dynamic_properties:
        extra.append("dynamicProperties")
    if shape.controls_typed:
        extra.append("sample_type")
    with (tables / "samples.tsv").open("w", encoding="utf-8") as out:
        out.write(
            "sampleID\teventID\tdecimalLatitude\tdecimalLongitude\tcoordinateUncertaintyInMeters"
            "\teventDate\tminimumDepthInMeters\tmaximumDepthInMeters\ttemperature_C\tlocality"
            + "".join(f"\t{name}" for name in extra)
            + "\n"
        )
        for s in range(SAMPLES):
            readings = [f"{(s * (m + 3)) % 997 / 7:.3f}" for m in range(shape.measurements)]
            notes = [f"cast {n} station {s % 37}" for n in range(shape.notes)]
            if shape.source_dynamic_properties:
                notes.append(_source_dynamic_properties(s))
            if shape.controls_typed:
                notes.append("negative control" if s % CONTROL_EVERY == 0 else "seawater")
            out.write(
                f"PS{s}\tPS{s}\t{47.55 + (s % 100) * 0.002:.4f}\t-122.4500\t100"
                f"\t2025-06-{1 + s % 28:02d}\t{s % 7}\t{s % 7}\t{10 + s % 5}.{s % 10}\tElliott Bay"
                + "".join(f"\t{value}" for value in [*readings, *notes])
                + "\n"
            )
    with (tables / "counts.tsv").open("w", encoding="utf-8") as out:
        if shape.wide_counts:
            out.write("featureID" + "".join(f"\tPS{s}" for s in range(SAMPLES)) + "\n")
            for f in range(features):
                counts = "".join(f"\t{_count(f, s)}" for s in range(SAMPLES))
                out.write(f"asv{f}{counts}\n")
        else:
            out.write("sampleID\tfeatureID\tcount\n")
            for f in range(features):
                out.writelines(f"PS{s}\tasv{f}\t{_count(f, s)}\n" for s in range(SAMPLES))
    answers = yaml.safe_load((CASE / "answers.yaml").read_text(encoding="utf-8"))
    answers["controls"] = {}
    if shape.controls_typed:
        answers["filters"] |= {
            "sample_metadata": "tables/samples.tsv",
            "sample_type_col": "sample_type",
        }
    if shape.every_row_corrected:
        _correct_every_row(directory, features)
    (directory / "answers.yaml").write_text(yaml.safe_dump(answers), encoding="utf-8")
    (directory / "conversion.yaml").write_text(yaml.safe_dump({"steps": []}), encoding="utf-8")
    shutil.copy(CASE / "resolved_taxonomy.tsv", directory / "resolved_taxonomy.tsv")


def _correct_every_row(directory: Path, features: int) -> None:
    confirmed = directory / "confirmed"
    confirmed.mkdir()
    with (confirmed / "derived_values.tsv").open("w", encoding="utf-8") as out:
        out.write("sampleID\tfeatureID\tdecimalLongitude\tprovenance\tconfirmed\n")
        for f in range(features):
            if "g__Homo" in LINEAGES[f % len(LINEAGES)][1]:
                continue
            out.writelines(
                f"PS{s}\tasv{f}\t-122.4501\tstation log gives the longitude\tA Researcher\n"
                for s in range(SAMPLES)
                if s % CONTROL_EVERY
            )


ASSEMBLE = [
    "assemble",
    "--counts",
    "tables/counts.tsv",
    "--features",
    "tables/features.tsv",
    "--samples",
    "tables/samples.tsv",
]
BUILD = ["build", "--automatic"]
COMPARE = ["replay", "--compare", "archive/dwca.zip", "archive/dwca.zip"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a synthetic conversion directory.")
    parser.add_argument("directory", type=Path)
    parser.add_argument("rows", type=int)
    parser.add_argument("--wide", action="store_true")
    args = parser.parse_args()
    write_conversion(args.directory, args.rows, WIDE if args.wide else NARROW)


if __name__ == "__main__":
    main()
