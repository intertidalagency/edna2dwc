from __future__ import annotations

import pytest

from tests.make_docs import GENERATED, render_page


@pytest.mark.parametrize("path", GENERATED, ids=lambda path: path.name)
def test_each_generated_page_matches_the_code_it_comes_from(path):
    assert path.read_text(encoding="utf-8") == render_page(path), (
        f"docs/{path.name} is out of date: run `just docs`"
    )
