from __future__ import annotations

import ast
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import pytest

from edna2dwc.cli.common import CommandLineError
from edna2dwc.conversion import stages
from edna2dwc.reproduce.environment import READER_PACKAGES
from tests.paths import INPUT_FIXTURES

FORMATS = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "convert-edna-to-dwc"
    / "references"
    / "formats"
)
FIXTURES = {
    "excel.md": ["multisheet.xlsx"],
    "qiime2.md": ["table.qza", "sample.qza"],
    "biom.md": ["sample_v1.biom"],
    "phyloseq.md": ["sample_phyloseq.rds"],
}
BLOCK = re.compile(r"```(python|r|bash)\n(.*?)```", flags=re.DOTALL)


def _blocks(page: str, language: str) -> list[str]:
    text = (FORMATS / page).read_text(encoding="utf-8")
    return [body for lang, body in BLOCK.findall(text) if lang == language]


def _phyloseq_installed() -> bool:
    if shutil.which("Rscript") is None:
        return False
    check = subprocess.run(
        ["Rscript", "-e", 'quit(status=if(requireNamespace("phyloseq",quietly=TRUE)) 0 else 1)'],
        capture_output=True,
        check=False,
    )
    return check.returncode == 0


def test_every_format_page_has_a_fixture_to_run_against():
    assert set(FIXTURES) == {page.name for page in FORMATS.glob("*.md")}


@pytest.mark.parametrize("page", sorted(FIXTURES))
def test_a_snippet_imports_only_what_a_reader_script_may(page):
    allowed = set(READER_PACKAGES) | set(sys.stdlib_module_names) | {"__future__"}
    for block in _blocks(page, "python"):
        for node in ast.walk(ast.parse(block)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert {name.split(".")[0] for name in names} <= allowed, (page, names)


@pytest.mark.parametrize("page", sorted(FIXTURES))
def test_a_snippet_reads_its_fixture_into_tables_that_assemble_joins(
    page, tmp_path, monkeypatch, run_cli
):
    if _blocks(page, "r") and not _phyloseq_installed():
        pytest.skip("needs Rscript with the phyloseq package")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "raw").mkdir()
    for name in FIXTURES[page]:
        shutil.copy(INPUT_FIXTURES / name, tmp_path / "raw" / name)
    (tmp_path / "conversion.yaml").write_text("steps: []\n", encoding="utf-8")

    for interpreter, language, suffix in ((sys.executable, "python", "py"), ("Rscript", "r", "R")):
        if blocks := _blocks(page, language):
            script = tmp_path / f"read_inputs.{suffix}"
            script.write_text("\n".join(blocks), encoding="utf-8")
            subprocess.run([interpreter, str(script)], check=True, capture_output=True)

    commands = [
        line for block in _blocks(page, "bash") for line in block.splitlines() if line.strip()
    ]
    assert commands, f"{page} shows no assemble command"
    for line in commands:
        result = run_cli(shlex.split(line)[1:])
        assert result.exit_code == 0, result.render()
        assert "satisfies the intermediate table's schema" in result.text


READING_INPUTS = FORMATS.parent / "reading-inputs.md"
COUNTS = {
    "long": "sampleID,featureID,count\nS1,asv1,5\nS2,asv2,3\nS2,asv1,0\n",
    "wide": "featureID,S1,S2\nasv1,5,0\nasv2,0,3\n",
    "wide with a marker": "featureID,marker,S1,S2\nasv1,12S,5,0\nasv2,12S,0,3\n",
}
FEATURES = {
    "a lineage": "featureID,taxonomy,confidence\nasv1,Animalia;Chordata,0.98\nasv2,unassigned,0.4\n",
    "rank columns": "featureID,kingdom,phylum,confidence\nasv1,Animalia,Chordata,0.98\nasv2,NA,NA,0.4\n",
}
SAMPLES = "sampleID,eventDate,decimalLatitude,decimalLongitude\nS1,2021-06-01,49.2,-123.1\nS2,2021-06-02,49.3,-123.2\n"
SEQUENCES = ">asv1\nACGTACGT\n>asv2\nTTGACCAA\n"


def _documented_assemble() -> list[str]:
    text = READING_INPUTS.read_text(encoding="utf-8")
    (line,) = [
        line
        for lang, body in BLOCK.findall(text)
        if lang == "bash"
        for line in body.splitlines()
        if line.startswith("edna2dwc assemble")
    ]
    return shlex.split(line)[1:]


def _conversion(tmp_path, monkeypatch, tables: dict[str, str]) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "conversion.yaml").write_text("steps: []\n", encoding="utf-8")
    (tmp_path / "tables").mkdir()
    for name, body in tables.items():
        (tmp_path / "tables" / name).write_text(body, encoding="utf-8")
    return tmp_path


def _table(path: Path) -> list[dict[str, str]]:
    header, *rows = [line.split("\t") for line in path.read_text().splitlines()]
    return [dict(zip(header, row, strict=True)) for row in rows]


@pytest.mark.parametrize("features", sorted(FEATURES))
@pytest.mark.parametrize("counts", sorted(COUNTS))
def test_every_documented_layout_assembles_with_the_documented_command(
    counts, features, tmp_path, monkeypatch, run_cli
):
    directory = _conversion(
        tmp_path,
        monkeypatch,
        {
            "counts.csv": COUNTS[counts],
            "taxonomy.csv": FEATURES[features],
            "samples.csv": SAMPLES,
            "sequences.fasta": SEQUENCES,
        },
    )
    result = run_cli(_documented_assemble())
    assert result.exit_code == 0, result.render()
    assert "satisfies the intermediate table's schema" in result.text
    rows = {(r["sampleID"], r["featureID"]): r for r in _table(directory / "occurrence_long.tsv")}
    assert set(rows) == {("S1", "asv1"), ("S2", "asv2")}
    assert rows["S1", "asv1"]["sequence"] == "ACGTACGT"
    assert rows["S2", "asv2"]["eventDate"] == "2021-06-02"
    assert rows["S2", "asv2"]["confidence"] == "0.4"
    lineage = "taxonomy" if features == "a lineage" else "kingdom"
    assert rows["S2", "asv2"][lineage] in {"unassigned", "NA"}


def test_a_wide_count_table_with_a_text_column_is_sent_to_features(tmp_path, monkeypatch, run_cli):
    _conversion(
        tmp_path,
        monkeypatch,
        {
            "counts.csv": "featureID,S1,notes\nasv1,5,kept\n",
            "taxonomy.csv": FEATURES["a lineage"],
        },
    )
    with pytest.raises(CommandLineError) as error:
        run_cli(["assemble", "--counts", "tables/counts.csv", "--features", "tables/taxonomy.csv"])
    assert "--features" in str(error.value)


def test_a_key_with_no_counterpart_keeps_its_row_and_is_reported(tmp_path, monkeypatch, run_cli):
    directory = _conversion(
        tmp_path,
        monkeypatch,
        {
            "counts.csv": COUNTS["long"],
            "taxonomy.csv": FEATURES["a lineage"],
            "samples.csv": "sampleID,eventDate\nS1,2021-06-01\n",
        },
    )
    result = run_cli(
        [
            "assemble",
            "--counts",
            "tables/counts.csv",
            "--features",
            "tables/taxonomy.csv",
            "--samples",
            "tables/samples.csv",
        ]
    )
    assert "JOIN_METADATA_MISSING" in result.text
    assert len(_table(directory / "occurrence_long.tsv")) == 2


def _per_marker_tables(*, features_marker: bool) -> tuple[dict[str, str], list[str]]:
    tables, argv = {}, ["assemble"]
    for marker, feature, taxon in (("12S", "a1", "Chordata"), ("COI", "c1", "Arthropoda")):
        tables[f"counts_{marker}.csv"] = f"featureID,marker,S1\n{feature},{marker},3\n"
        tables[f"taxonomy_{marker}.csv"] = (
            f"featureID,marker,taxonomy\n{feature},{marker},{taxon}\n"
            if features_marker
            else f"featureID,taxonomy\n{feature},{taxon}\n"
        )
        argv += ["--counts", f"tables/counts_{marker}.csv"]
    for marker in ("12S", "COI"):
        argv += ["--features", f"tables/taxonomy_{marker}.csv"]
    return tables, argv


def test_one_count_and_one_taxonomy_table_per_marker_assemble(tmp_path, monkeypatch, run_cli):
    tables, argv = _per_marker_tables(features_marker=False)
    directory = _conversion(tmp_path, monkeypatch, tables)
    result = run_cli(argv)
    assert result.exit_code == 0, result.render()
    markers = {r["featureID"]: r["marker"] for r in _table(directory / "occurrence_long.tsv")}
    assert markers == {"a1": "12S", "c1": "COI"}


def test_a_marker_column_on_a_taxonomy_table_says_it_belongs_on_the_counts(
    tmp_path, monkeypatch, run_cli
):
    tables, argv = _per_marker_tables(features_marker=True)
    _conversion(tmp_path, monkeypatch, tables)
    with pytest.raises(CommandLineError) as error:
        run_cli(argv)
    assert "--counts tables only" in str(error.value)


def test_the_opening_names_the_stages_in_order():
    skill = (FORMATS.parent.parent / "SKILL.md").read_text(encoding="utf-8")
    opening = skill.split("## Open the conversion")[1].split("\nThen run")[0]
    named = re.findall(r"^\s*\d\. \*\*(\w+)\*\*", opening, flags=re.MULTILINE)
    assert named == list(stages.PURPOSES)
