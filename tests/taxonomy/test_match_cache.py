from __future__ import annotations

import json
import os

import pytest

from edna2dwc.taxonomy.match_cache import MatchCache


def test_a_save_cut_off_before_it_finishes_leaves_the_last_whole_file(tmp_path, monkeypatch):
    path = tmp_path / "cache" / "match_cache.json"
    cache = MatchCache(path.parent, path.name)
    cache.add({"Aaptos": ["first"]})
    cache.save()

    def cut_off(source, destination):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", cut_off)
    cache.add({"Acartia": ["second"]})
    with pytest.raises(OSError, match="disk full"):
        cache.save()

    assert json.loads(path.read_text(encoding="utf-8")) == {"Aaptos": ["first"]}


def test_a_cache_without_a_directory_keeps_its_entries_in_memory_only(tmp_path):
    cache = MatchCache(None, "match_cache.json")
    cache.add({"Aaptos": ["first"]})
    cache.save()

    assert cache["Aaptos"] == ["first"]
    assert not list(tmp_path.iterdir())
