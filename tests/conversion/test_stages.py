from __future__ import annotations

from edna2dwc.conversion import stages


def test_the_overview_lists_every_stage_in_order():
    overview = stages.overview()
    assert [line.split("**")[1] for line in overview] == list(stages.PURPOSES)


def test_build_stays_at_convert_until_an_audit_is_recorded(tmp_path):
    assert stages.build_stage(tmp_path) == stages.CONVERT
    (tmp_path / "audit_record.json").write_text("{}", encoding="utf-8")
    assert stages.build_stage(tmp_path) == stages.CHECK
