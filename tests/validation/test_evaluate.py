from __future__ import annotations

from edna2dwc.validation.evaluate import bundled_adjudications


def test_the_adjudications_are_read_from_the_bundled_answers(tmp_path):
    bundle = tmp_path / "archive" / "reproduce"
    bundle.mkdir(parents=True)
    (bundle / "answers.yaml").write_text(
        "adjudications:\n  ON_LAND: {status: accepted, provenance: PI}\n"
    )
    assert bundled_adjudications(tmp_path / "archive") == bundle / "answers.yaml"
