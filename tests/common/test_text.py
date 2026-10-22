from __future__ import annotations

from edna2dwc.common.text import first_few


def test_first_few_names_every_item_up_to_the_limit():
    assert first_few(["a", "b"], 2) == "a, b"


def test_first_few_counts_the_items_past_the_limit():
    assert first_few(["a", "b", "c", "d"], 2) == "a, b and 2 more"
