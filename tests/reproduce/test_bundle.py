from __future__ import annotations

from pathlib import Path

import pytest

from edna2dwc.common.tsv import write_tsv
from edna2dwc.dwca import writer
from edna2dwc.reproduce import bundle, steps_log
from tests import manifests


@pytest.fixture
def project_dir(tmp_path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "conversion.yaml").write_text("steps: []\n", encoding="utf-8")
    for name in (
        "answers.yaml",
        "occurrence_long.tsv",
        "resolved_taxonomy.tsv",
        "excluded_rows_report.tsv",
        "term_states.tsv",
        "audit_record.json",
    ):
        (project / name).write_text(f"contents of {name}\n", encoding="utf-8")
    return project


@pytest.fixture
def packaged(tmp_path) -> Path:
    justfile = tmp_path / "justfile"
    justfile.write_text("replay:\n", encoding="utf-8")
    return justfile


def _collect(project_dir, packaged, **kwargs):
    return bundle.collect(project_dir, justfile_path=packaged, **kwargs)


def _errors(log) -> list[tuple[str, str]]:
    return [(f.code, f.message) for f in log.findings if f.severity == "error"]


def test_collect_gathers_every_artifact_a_replay_needs(project_dir, packaged):
    result = _collect(project_dir, packaged)

    assert "reproduce/conversion.yaml" in result.arcnames
    assert "reproduce/answers.yaml" in result.arcnames
    assert "reproduce/resolved_taxonomy.tsv" in result.arcnames
    assert "reproduce/justfile" in result.arcnames
    assert "reproduce/audit_record.json" in result.arcnames
    assert not result.log.has_errors()


def test_collect_carries_every_confirmed_sheet_and_no_proposal(project_dir, packaged):
    for sheet_dir in ("proposed", "confirmed"):
        (project_dir / sheet_dir).mkdir()
        (project_dir / sheet_dir / "taxa.tsv").write_text("featureID\n", encoding="utf-8")

    result = _collect(project_dir, packaged)

    assert "reproduce/confirmed/taxa.tsv" in result.arcnames
    assert not any(name.startswith("reproduce/proposed/") for name in result.arcnames)


def test_collect_leaves_out_every_file_a_replay_writes_again(project_dir, packaged):
    for name in ("term_mapping.tsv", "findings.json", "dwc_terms.json"):
        (project_dir / name).write_text("{}", encoding="utf-8")

    result = _collect(project_dir, packaged)

    written_again = (
        "occurrence_long.tsv",
        "excluded_rows_report.tsv",
        "term_states.tsv",
        "term_mapping.tsv",
        "findings.json",
        "dwc_terms.json",
    )
    assert not set(result.arcnames) & {f"reproduce/{name}" for name in written_again}
    assert not any(name in f.message for f in result.log.findings for name in written_again)


def test_recorded_raw_inputs_are_read_from_conversion_yaml(tmp_path):
    config = tmp_path / "conversion.yaml"
    config.write_text("raw_inputs:\n- data/table.biom\n", encoding="utf-8")

    assert bundle.recorded_raw_inputs(config) == [Path("data/table.biom")]


def test_no_recorded_raw_inputs_is_an_empty_list(tmp_path):
    config = tmp_path / "conversion.yaml"
    config.write_text("steps: []\n", encoding="utf-8")

    assert bundle.recorded_raw_inputs(config) == []


def test_a_file_the_recipe_references_by_path_is_carried(project_dir, packaged):
    (project_dir / "adjudications.yaml").write_text("- code: ON_LAND\n", encoding="utf-8")

    result = _collect(project_dir, packaged, config_inputs=[Path("adjudications.yaml")])

    assert "reproduce/adjudications.yaml" in result.arcnames


def test_a_referenced_file_that_is_absent_is_an_error_not_a_silent_gap(project_dir, packaged):
    result = _collect(project_dir, packaged, config_inputs=[Path("adjudications.yaml")])

    assert _errors(result.log) == [
        (
            "BUNDLE_ARTIFACT_MISSING",
            (
                "answers.yaml points at adjudications.yaml, which does not exist, so a replay "
                "cannot read it"
            ),
        )
    ]


def test_a_referenced_file_outside_the_bundle_is_disclosed_not_flattened(project_dir, packaged):
    result = _collect(project_dir, packaged, config_inputs=[Path("../shared/adj.yaml")])

    assert not any(name.endswith("adj.yaml") for name in result.arcnames)
    assert _errors(result.log) == [
        (
            "BUNDLE_ARTIFACT_MISSING",
            (
                "answers.yaml points at ../shared/adj.yaml, which is outside the conversion "
                "directory, so no bundled copy would be where the recorded command looks for it"
            ),
        )
    ]


def test_a_missing_required_artifact_is_an_error_not_a_silent_gap(project_dir, packaged):
    (project_dir / "resolved_taxonomy.tsv").unlink()

    result = _collect(project_dir, packaged)

    assert _errors(result.log) == [
        (
            "BUNDLE_ARTIFACT_MISSING",
            (
                "resolved_taxonomy.tsv is absent, so the bundle cannot replay (the taxonomy lock: "
                "build reads no register)"
            ),
        )
    ]
    assert "reproduce/resolved_taxonomy.tsv" not in result.arcnames


def test_a_missing_answers_file_is_an_error(project_dir, packaged):
    (project_dir / "answers.yaml").unlink()

    result = _collect(project_dir, packaged)

    assert _errors(result.log) == [
        (
            "BUNDLE_ARTIFACT_MISSING",
            (
                "answers.yaml is absent, so the bundle cannot replay (every answer a person gave "
                "about the dataset)"
            ),
        )
    ]


def test_every_vendored_script_is_carried(project_dir, packaged):
    scripts = project_dir / "scripts"
    scripts.mkdir()
    (scripts / "read_ena_export.py").write_text("print(1)\n", encoding="utf-8")
    (scripts / "patch_station_codes.py").write_text("print(2)\n", encoding="utf-8")

    result = _collect(project_dir, packaged)

    assert "reproduce/scripts/read_ena_export.py" in result.arcnames
    assert "reproduce/scripts/patch_station_codes.py" in result.arcnames


def test_a_bundled_script_no_step_runs_is_named(project_dir, packaged):
    scripts = project_dir / "scripts"
    scripts.mkdir()
    (scripts / "read_ena_export.py").write_text("print(1)\n", encoding="utf-8")
    (scripts / "try2.py").write_text("print(2)\n", encoding="utf-8")
    (project_dir / "conversion.yaml").write_text(
        "steps:\n"
        "- n: 1\n"
        "  command: python scripts/read_ena_export.py\n"
        "  script: scripts/read_ena_export.py\n"
        "  sha256: abc\n",
        encoding="utf-8",
    )

    result = _collect(project_dir, packaged)

    assert "reproduce/scripts/try2.py" in result.arcnames
    unrun = [f for f in result.log.findings if f.code == "BUNDLE_SCRIPT_NOT_RUN"]
    assert [f.severity for f in unrun] == ["info"]
    assert unrun[0].message == (
        "scripts/try2.py is bundled, but no step in conversion.yaml runs it: delete it "
        "unless a reader script imports it"
    )


def test_raw_inputs_are_carried_and_a_recipe_with_no_steps_needs_none(project_dir, packaged):
    result = _collect(project_dir, packaged)
    assert not result.log.findings

    source = project_dir / "table.biom"
    source.write_text("{}", encoding="utf-8")
    with_raw = _collect(project_dir, packaged, raw_inputs=[source])

    assert "reproduce/table.biom" in with_raw.arcnames
    assert not with_raw.log.findings


def test_a_raw_input_inside_the_conversion_directory_is_carried_where_its_command_names_it(
    project_dir, packaged
):
    (project_dir / "input").mkdir()
    (project_dir / "input" / "wide.csv").write_text("a,b\n", encoding="utf-8")

    result = _collect(project_dir, packaged, raw_inputs=[project_dir / "input" / "wide.csv"])

    assert "reproduce/input/wide.csv" in result.arcnames
    assert not result.log.has_errors()


def test_a_raw_input_outside_the_conversion_directory_is_an_error(project_dir, packaged, tmp_path):
    source = tmp_path / "input" / "wide.csv"
    source.parent.mkdir()
    source.write_text("a,b\n", encoding="utf-8")

    result = _collect(project_dir, packaged, raw_inputs=[source])

    assert not any(name.endswith("wide.csv") for name in result.arcnames)
    assert result.log.has_errors()
    assert any(str(source) in f.message for f in result.log.findings)


def test_a_raw_input_that_links_elsewhere_in_the_conversion_is_carried_under_its_own_name(
    project_dir, packaged
):
    (project_dir / "input").mkdir()
    target = project_dir / "input" / "wide.csv"
    target.write_text("a,b\n", encoding="utf-8")
    link = project_dir / "latest.csv"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("this platform can't create symlinks without extra privileges")

    result = _collect(project_dir, packaged, raw_inputs=[link])

    assert "reproduce/latest.csv" in result.arcnames
    assert not result.log.has_errors()


def test_a_raw_input_on_another_drive_is_an_error_not_a_crash(
    project_dir, packaged, tmp_path, monkeypatch
):
    source = tmp_path / "wide.csv"
    source.write_text("a,b\n", encoding="utf-8")

    def relpath_across_drives(path, start):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(bundle.os.path, "relpath", relpath_across_drives)
    result = _collect(project_dir, packaged, raw_inputs=[source])

    assert not any(name.endswith("wide.csv") for name in result.arcnames)
    assert any(str(source) in f.message and f.severity == "error" for f in result.log.findings)


def test_every_raw_input_is_carried_however_large(project_dir, packaged):
    (project_dir / "input").mkdir()
    sizes = {"taxa.tsv.gz": 60, "counts.rds": 40}
    for name, megabytes in sizes.items():
        with (project_dir / "input" / name).open("wb") as raw:
            raw.truncate(megabytes * 1024 * 1024)

    result = _collect(
        project_dir, packaged, raw_inputs=[project_dir / "input" / name for name in sizes]
    )

    assert {f"reproduce/input/{name}" for name in sizes} <= set(result.arcnames)
    assert not result.log.findings


def test_a_named_raw_input_that_does_not_exist_is_an_error(project_dir, packaged, tmp_path):
    result = _collect(project_dir, packaged, raw_inputs=[tmp_path / "gone.biom"])

    assert result.log.has_errors()


def test_write_copies_every_collected_file_under_the_archive(project_dir, packaged, tmp_path):
    scripts = project_dir / "scripts"
    scripts.mkdir()
    (scripts / "reader.py").write_text("print(1)\n", encoding="utf-8")
    result = _collect(project_dir, packaged)
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()

    written = bundle.write(result, archive_dir)

    assert (archive_dir / "reproduce" / "conversion.yaml").exists()
    assert (archive_dir / "reproduce" / "scripts" / "reader.py").exists()
    assert (archive_dir / "reproduce" / "conversion.yaml").read_text() == "steps: []\n"
    assert written == result.arcnames


def _built_archive(tmp_path):
    core = tmp_path / "core.tsv"
    write_tsv(
        [{"occurrenceID": "ds_s1_f1", "scientificName": "A", "basisOfRecord": "MaterialSample"}],
        core,
        columns=["occurrenceID", "scientificName", "basisOfRecord"],
    )
    metadata = manifests.required_manifest()
    archive_dir = tmp_path / "archive"
    writer.write_archive(
        core_path=core,
        extensions={},
        manifest=metadata,
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table={
            term: {"uri": f"http://rs.tdwg.org/dwc/terms/{term}"}
            for term in ("occurrenceID", "scientificName", "basisOfRecord")
        },
        out_dir=archive_dir,
    )
    return archive_dir


def test_check_declared_tables_passes_an_archive_with_every_table(tmp_path):
    assert not bundle.check_declared_tables(_built_archive(tmp_path)).findings


def test_check_declared_tables_reports_a_table_meta_xml_declares_that_is_missing(tmp_path):
    archive_dir = _built_archive(tmp_path)
    (archive_dir / "occurrence.txt").rename(archive_dir / "occurrence.tsv")

    log = bundle.check_declared_tables(archive_dir)

    assert _errors(log) == [
        (
            "BUNDLE_ARTIFACT_MISSING",
            (
                f"meta.xml declares occurrence.txt, which is not in {archive_dir}, so the rewritten "
                "zip leaves it out; restore the file under that name"
            ),
        )
    ]


def _step(command: str, script: str = "scripts/read_inputs.py") -> steps_log.Step:
    return steps_log.Step(n=1, command=command, script=script, sha256="")


def _write_script(project_dir: Path, body: str) -> None:
    (project_dir / "scripts").mkdir(exist_ok=True)
    (project_dir / "scripts" / "read_inputs.py").write_text(body, encoding="utf-8")


def _recipe_errors(project_dir: Path, steps, raw_inputs=()) -> list[str]:
    log = bundle.check_recipe(project_dir, steps, [Path(p) for p in raw_inputs])
    return [f.message for f in log.findings if f.severity == "error"]


def test_a_script_reading_a_fixed_place_is_an_error(project_dir):
    _write_script(project_dir, "import pandas\npandas.read_csv('/work/input/data/asv.csv')\n")

    errors = _recipe_errors(project_dir, [_step("python scripts/read_inputs.py")], ["raw/x.csv"])

    assert len(errors) == 1
    assert "scripts/read_inputs.py" in errors[0]
    assert "/work/input/data/asv.csv" in errors[0]
    assert "--raw" in errors[0]


def test_a_script_reading_above_the_conversion_directory_is_an_error(project_dir):
    _write_script(project_dir, 'open("../input/OTUtable.csv")\n')

    errors = _recipe_errors(project_dir, [_step("python scripts/read_inputs.py")], ["raw/x.csv"])

    assert any("../input/OTUtable.csv" in message for message in errors)


def test_a_script_reading_a_file_no_raw_input_names_is_an_error(project_dir):
    (project_dir / "input").mkdir()
    (project_dir / "input" / "asv.csv").write_text("a\n", encoding="utf-8")
    _write_script(project_dir, "open('input/asv.csv')\nopen('tables/counts.csv', 'w')\n")

    errors = _recipe_errors(project_dir, [_step("python scripts/read_inputs.py")], ["raw/x.csv"])

    assert len(errors) == 1
    assert "input/asv.csv" in errors[0]
    assert "tables/counts.csv" not in errors[0]


def test_a_script_reading_only_recorded_inputs_and_tables_passes(project_dir):
    (project_dir / "raw").mkdir()
    (project_dir / "raw" / "asv.csv").write_text("a\n", encoding="utf-8")
    _write_script(
        project_dir,
        "import pandas\nframe = pandas.read_csv('raw/asv.csv')\n"
        "frame.to_csv('tables/counts.csv')\nurl = 'https://example.org/a/b'\nsep = '/'\n",
    )

    assert (
        _recipe_errors(
            project_dir, [_step("python scripts/read_inputs.py raw/asv.csv")], ["raw/asv.csv"]
        )
        == []
    )


def test_a_command_naming_a_file_that_is_not_recorded_is_an_error(project_dir):
    (project_dir / "input").mkdir()
    (project_dir / "input" / "asv.csv").write_text("a\n", encoding="utf-8")
    _write_script(project_dir, "pass\n")

    errors = _recipe_errors(
        project_dir, [_step("python scripts/read_inputs.py input/asv.csv")], ["raw/x.csv"]
    )

    assert len(errors) == 1
    assert "input/asv.csv" in errors[0]


def test_a_command_naming_a_fixed_place_is_an_error_whether_or_not_it_exists(project_dir):
    _write_script(project_dir, "pass\n")

    errors = _recipe_errors(
        project_dir, [_step("python scripts/read_inputs.py /work/input/data")], ["raw/x.csv"]
    )

    assert any("/work/input/data" in message for message in errors)


def test_a_command_naming_a_directory_holding_a_raw_input_passes(project_dir):
    (project_dir / "raw").mkdir()
    _write_script(project_dir, "pass\n")

    assert (
        _recipe_errors(
            project_dir, [_step("python scripts/read_inputs.py raw/ tables")], ["raw/x.csv"]
        )
        == []
    )


def test_script_steps_with_no_raw_input_at_all_are_an_error(project_dir):
    _write_script(project_dir, "pass\n")

    errors = _recipe_errors(project_dir, [_step("python scripts/read_inputs.py")])

    assert any("record-step --raw" in message for message in errors)


def test_a_raw_input_under_tables_is_an_error(project_dir):
    _write_script(project_dir, "pass\n")

    errors = _recipe_errors(
        project_dir, [_step("python scripts/read_inputs.py")], ["tables/counts.csv"]
    )

    assert any("tables/counts.csv" in message for message in errors)


def test_collect_checks_the_recipe_conversion_yaml_records(project_dir, packaged):
    _write_script(project_dir, "open('/work/input/data/asv.csv')\n")
    (project_dir / "conversion.yaml").write_text(
        "steps:\n- n: 1\n  command: python scripts/read_inputs.py\n"
        "  script: scripts/read_inputs.py\n  sha256: ''\n",
        encoding="utf-8",
    )

    result = _collect(project_dir, packaged)

    assert any("/work/input/data/asv.csv" in f.message for f in result.log.findings)
    assert result.log.has_errors()
