from __future__ import annotations

import json
from pathlib import Path

import pytest

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.tsv import write_tsv
from edna2dwc.dwca import writer
from edna2dwc.review.audit import record_audit
from edna2dwc.validation import credentials, gbif_validator
from tests import manifests

TERM_TABLE = {
    "occurrenceID": {
        "uri": "http://rs.tdwg.org/dwc/terms/occurrenceID",
        "priority_tier": "required",
    },
    "scientificName": {
        "uri": "http://rs.tdwg.org/dwc/terms/scientificName",
        "priority_tier": "required",
    },
    "basisOfRecord": {"uri": "http://rs.tdwg.org/dwc/terms/basisOfRecord"},
    "eventDate": {
        "uri": "http://rs.tdwg.org/dwc/terms/eventDate",
        "format": "iso8601_date",
        "priority_tier": "required",
    },
    "recordedBy": {
        "uri": "http://rs.tdwg.org/dwc/terms/recordedBy",
        "priority_tier": "strongly_recommended",
    },
}

CORE_COLUMNS = ["occurrenceID", "scientificName", "basisOfRecord"]


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def terms_table_path(tmp_path) -> Path:
    path = tmp_path / "dwc_terms.json"
    path.write_text(json.dumps(TERM_TABLE), encoding="utf-8")
    return path


@pytest.fixture
def archive_dir(tmp_path) -> Path:
    return _built_archive(tmp_path, tmp_path / "archive")


def _built_archive(tmp_path: Path, out_dir: Path) -> Path:
    core_path = tmp_path / "occurrence.tsv"
    write_tsv(
        [
            {"occurrenceID": "ds:s1:f1", "scientificName": "A", "basisOfRecord": "MaterialSample"},
            {"occurrenceID": "ds:s1:f2", "scientificName": "B", "basisOfRecord": "MaterialSample"},
        ],
        core_path,
        columns=CORE_COLUMNS,
    )
    writer.write_archive(
        core_path=core_path,
        extensions={},
        manifest=manifests.required_manifest(),
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
    )
    return out_dir


def test_evaluate_names_each_missing_term_on_its_page_and_fails_without_asking_gbif(
    run_cli, archive_dir, terms_table_path, monkeypatch
):
    looked_up = []
    monkeypatch.setattr(credentials, "gbif_credentials", lambda: looked_up.append(1))

    result = run_cli(
        ["evaluate", str(archive_dir), "--terms-table", str(terms_table_path), "--json"]
    )

    assert result.exit_code == 1
    assert "EVALUATION.md" in result.text
    assert "--gbif" in result.text
    assert looked_up == []
    body = json.loads(result.render())
    assert [(m["term"], m["tier"], m["filled"]) for m in body["missing_terms"]] == [
        ("eventDate", "required", "0 of 2 rows"),
        ("recordedBy", "strongly recommended", "0 of 2 rows"),
    ]
    checks = {c["name"]: c for c in body["checks"]}
    assert body["all_checks_passed"] is False
    assert body["passes_gbif_obis"] is None
    assert checks["Every required term is filled on every row"]["passed"] is False
    assert "No fabricated values" not in checks
    assert checks["GBIF validator reports no errors"]["passed"] is None
    assert checks["OBIS checks report no errors"]["passed"] is not None
    page = (archive_dir / "EVALUATION.md").read_text(encoding="utf-8")
    assert page.startswith(f"# Evaluation of {archive_dir}\n\n- Records: 2\n")
    assert "| `eventDate` | required |" in page
    assert (archive_dir / "EVALUATION.html").read_text(encoding="utf-8").startswith("<!DOCTYPE")
    assert "0 of 2 rows" in page


def test_evaluate_lists_a_required_term_blank_on_most_rows_with_its_share(
    run_cli, tmp_path, terms_table_path
):
    core_path = tmp_path / "occurrence.tsv"
    write_tsv(
        [
            {
                "occurrenceID": "ds:s1:f1",
                "scientificName": "A",
                "basisOfRecord": "MaterialSample",
                "eventDate": "2024-01-15",
            },
            {
                "occurrenceID": "ds:s1:f2",
                "scientificName": "B",
                "basisOfRecord": "MaterialSample",
                "eventDate": "",
            },
        ],
        core_path,
        columns=[*CORE_COLUMNS, "eventDate"],
    )
    archive_dir = tmp_path / "archive"
    writer.write_archive(
        core_path=core_path,
        extensions={},
        manifest=manifests.required_manifest(),
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=archive_dir,
    )

    result = run_cli(
        ["evaluate", str(archive_dir), "--terms-table", str(terms_table_path), "--json"]
    )

    body = json.loads(result.render())
    missing = {m["term"]: m for m in body["missing_terms"]}
    assert missing["eventDate"]["filled"] == "1 of 2 rows"
    checks = {c["name"]: c for c in body["checks"]}
    assert checks["Every required term is filled on every row"]["passed"] is False


def test_evaluate_reads_the_term_state_recorded_for_a_missing_term(
    run_cli, archive_dir, terms_table_path
):
    write_tsv(
        [
            {"term": "eventDate", "state": "Impossible", "evidence": "no date column anywhere"},
            {"term": "recordedBy", "state": "Ask", "evidence": "the methods PDF may name them"},
        ],
        Path("term_states.tsv"),
        columns=["term", "state", "evidence"],
    )

    result = run_cli(
        [
            "evaluate",
            str(archive_dir),
            "--terms-table",
            str(terms_table_path),
            "--json",
        ]
    )

    missing = {m["term"]: m for m in json.loads(result.render())["missing_terms"]}
    assert missing["eventDate"]["state"] == "Impossible"
    assert missing["eventDate"]["evidence"] == "no date column anywhere"
    checks = {c["name"]: c for c in json.loads(result.render())["checks"]}
    assert checks["Every term has a recorded state"]["passed"] is True


def test_evaluate_reads_the_conversion_directory_the_archive_was_built_in(
    run_cli, tmp_path, terms_table_path, monkeypatch
):
    conversion = tmp_path / "conversion"
    conversion.mkdir()
    (conversion / "answers.yaml").write_text("out_dir: out/archive\n", encoding="utf-8")
    write_tsv(
        [
            {"term": "eventDate", "state": "Impossible", "evidence": "no date column anywhere"},
            {"term": "recordedBy", "state": "Ask", "evidence": "the methods PDF may name them"},
        ],
        conversion / "term_states.tsv",
        columns=["term", "state", "evidence"],
    )
    archive = conversion / "out" / "archive"
    archive.parent.mkdir()
    _built_archive(tmp_path, archive)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = run_cli(["evaluate", str(archive), "--terms-table", str(terms_table_path), "--json"])

    checks = {c["name"]: c for c in json.loads(result.render())["checks"]}
    assert checks["Every term has a recorded state"]["passed"] is True


def test_evaluate_lists_a_term_the_archive_requires_whatever_its_state(
    run_cli, archive_dir, tmp_path
):
    terms_table_path = tmp_path / "required_terms.json"
    terms_table_path.write_text(
        json.dumps(
            {**TERM_TABLE, "occurrenceID": {**TERM_TABLE["occurrenceID"], "tier": "required"}}
        ),
        encoding="utf-8",
    )
    (archive_dir / "occurrence.txt").write_text(
        "scientificName\tbasisOfRecord\nA\tMaterialSample\n", encoding="utf-8"
    )
    write_tsv(
        [{"term": "occurrenceID", "state": "Not-applicable", "evidence": "hand-edited"}],
        Path("term_states.tsv"),
        columns=["term", "state", "evidence"],
    )

    result = run_cli(
        [
            "evaluate",
            str(archive_dir),
            "--terms-table",
            str(terms_table_path),
            "--json",
        ]
    )

    missing = {m["term"]: m for m in json.loads(result.render())["missing_terms"]}
    assert missing["occurrenceID"]["state"] == "Not-applicable"


def test_evaluate_gives_each_missing_term_its_build_tier(run_cli, archive_dir, tmp_path):
    term_table = {
        **TERM_TABLE,
        "eventDate": {**TERM_TABLE["eventDate"], "tier": "required_if_occurrence_core"},
    }
    terms_table_path = tmp_path / "terms_with_build_tier.json"
    terms_table_path.write_text(json.dumps(term_table), encoding="utf-8")

    result = run_cli(
        [
            "evaluate",
            str(archive_dir),
            "--terms-table",
            str(terms_table_path),
            "--json",
        ]
    )

    missing = {m["term"]: m for m in json.loads(result.render())["missing_terms"]}
    assert missing["eventDate"]["build_tier"] == "required if occurrence core"
    assert missing["recordedBy"]["build_tier"] == ""
    page = (archive_dir / "EVALUATION.md").read_text(encoding="utf-8")
    assert "| `eventDate` | required | required if occurrence core |" in page


def test_a_missing_strongly_recommended_term_is_named_but_does_not_block_readiness(
    run_cli, tmp_path, terms_table_path
):
    core_path = tmp_path / "occurrence.tsv"
    columns = [*CORE_COLUMNS, "eventDate"]
    write_tsv(
        [
            {
                "occurrenceID": "ds:s1:f1",
                "scientificName": "A",
                "basisOfRecord": "MaterialSample",
                "eventDate": "2021-06-01",
            }
        ],
        core_path,
        columns=columns,
    )
    out_dir = tmp_path / "archive"
    writer.write_archive(
        core_path=core_path,
        extensions={},
        manifest=manifests.required_manifest(),
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
    )

    result = run_cli(["evaluate", str(out_dir), "--terms-table", str(terms_table_path), "--json"])

    body = json.loads(result.render())
    checks = {c["name"]: c for c in body["checks"]}
    assert checks["Every required term is filled on every row"]["passed"] is True
    recommended = checks["Every strongly recommended term is filled on every row"]
    assert recommended["passed"] is False
    assert recommended["detail"] == "recordedBy (0/1 rows)"
    assert recommended["advisory"] is True
    assert "Every strongly recommended term is filled on every row" not in [
        c["name"] for c in body["checks"] if c["passed"] is False and not c["advisory"]
    ]


def _conversion_passing_every_check_but_gbif(tmp_path: Path) -> Path:
    core_path = tmp_path / "occurrence.tsv"
    columns = [*CORE_COLUMNS, "eventDate", "recordedBy"]
    write_tsv(
        [
            {
                "occurrenceID": "ds:s1:f1",
                "scientificName": "A",
                "basisOfRecord": "MaterialSample",
                "eventDate": "2021-06-01",
                "recordedBy": "R",
            }
        ],
        core_path,
        columns=columns,
    )
    out_dir = tmp_path / "archive"
    writer.write_archive(
        core_path=core_path,
        extensions={},
        manifest=manifests.required_manifest(),
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
    )
    write_tsv(
        [{"term": t, "state": "Filled", "evidence": "mapped occurrence table"} for t in columns],
        Path("term_states.tsv"),
        columns=["term", "state", "evidence"],
    )
    write_tsv(
        [{"source_column": c, "target": c, "basis": "exact"} for c in columns],
        Path("term_mapping.tsv"),
        columns=["source_column", "target", "basis"],
    )
    write_tsv(
        [{"sampleID": "s1", "featureID": "f1", "count": "3"}],
        Path("occurrence_long.tsv"),
        columns=["sampleID", "featureID", "count"],
    )
    return out_dir


def test_evaluate_passes_when_only_the_gbif_check_nobody_asked_for_is_unmeasured(
    run_cli, tmp_path, terms_table_path
):
    out_dir = _conversion_passing_every_check_but_gbif(tmp_path)

    result = run_cli(["evaluate", str(out_dir), "--terms-table", str(terms_table_path), "--json"])

    body = json.loads(result.render())
    unmeasured = [c["name"] for c in body["checks"] if c["passed"] is None]
    failed = [c["name"] for c in body["checks"] if c["passed"] is False]
    assert unmeasured == ["GBIF validator reports no errors"]
    assert _gbif_check(body)["advisory"] is True
    assert failed == []
    assert body["all_checks_passed"] is True
    assert result.exit_code == 0
    assert body["passes_gbif_obis"] is None
    assert body["missing_terms"] == []
    assert body["coverage"] == {"mapped": 5, "dynamicProperties": 0, "excluded": 0, "unmapped": 0}


def test_evaluate_with_gbif_submits_the_archive_and_reports_what_came_back(
    run_cli, archive_dir, terms_table_path, monkeypatch
):
    calls = []

    def fake_gbif(zip_path, *, credentials, client, adjudications):
        calls.append(zip_path)
        log = FindingsLog()
        log.add("GBIF_VALIDATOR_ISSUE", "TAXON_MATCH_NONE: 2 record(s)", severity="error")
        return log, [
            gbif_validator.GbifIssue(
                category="TAXON_MATCH_NONE", severity="error", affected_records=2
            )
        ]

    monkeypatch.setattr(gbif_validator, "run_gbif_validation", fake_gbif)

    result = run_cli(
        ["evaluate", str(archive_dir), "--gbif", "--terms-table", str(terms_table_path), "--json"]
    )

    assert calls == [archive_dir / "dwca.zip"]
    body = json.loads(result.render())
    assert body["gbif"] == {"ran": True, "detail": "", "errors": {"TAXON_MATCH_NONE": 2}}
    checks = {c["name"]: c for c in body["checks"]}
    assert checks["GBIF validator reports no errors"]["passed"] is False
    assert body["passes_gbif_obis"] is False
    page = (archive_dir / "EVALUATION.md").read_text(encoding="utf-8")
    assert "TAXON_MATCH_NONE" in page
    assert "GBIF and OBIS validators: reject" in page


def test_evaluate_reports_a_broken_archive_instead_of_a_traceback(
    run_cli, tmp_path, terms_table_path
):
    broken = tmp_path / "broken"
    broken.mkdir()

    result = run_cli(["evaluate", str(broken), "--terms-table", str(terms_table_path)])

    assert result.exit_code == 1
    page = (broken / "EVALUATION.md").read_text(encoding="utf-8")
    assert "eml.xml is missing" in page


def test_evaluate_lists_a_bundled_audit_finding_without_a_check(
    run_cli, archive_dir, terms_table_path
):
    (archive_dir / "reproduce").mkdir(exist_ok=True)
    record_audit(archive_dir / "reproduce" / "audit_record.json", ["invented a depth"])

    result = run_cli(
        [
            "evaluate",
            str(archive_dir),
            "--terms-table",
            str(terms_table_path),
            "--json",
        ]
    )

    body = json.loads(result.render())
    assert body["audit_findings"] == ["invented a depth"]
    assert not any("audit" in c["name"].lower() for c in body["checks"])
    page = (archive_dir / "EVALUATION.md").read_text(encoding="utf-8")
    assert "- invented a depth" in page


def _gbif_check(body: dict) -> dict:
    (check,) = [c for c in body["checks"] if c["name"] == "GBIF validator reports no errors"]
    return check


def test_a_gbif_check_asked_for_and_not_measured_still_decides_the_exit_code(
    run_cli, tmp_path, terms_table_path
):
    out_dir = _conversion_passing_every_check_but_gbif(tmp_path)

    result = run_cli(
        ["evaluate", str(out_dir), "--gbif", "--terms-table", str(terms_table_path), "--json"]
    )

    check = _gbif_check(json.loads(result.render()))
    assert check["passed"] is None
    assert check["advisory"] is False
    assert result.exit_code == 1
