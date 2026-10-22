from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import yaml

from edna2dwc.common.tsv import write_tsv
from edna2dwc.conversion import answers, artifacts
from edna2dwc.dwca.manifest import Manifest
from edna2dwc.taxonomy.resolve_taxonomy import OpenRegisters, register_clients

AAPTOS_RECORD = {
    "AphiaID": 132064,
    "scientificname": "Aaptos",
    "authority": "Gray, 1867",
    "status": "accepted",
    "rank": "Genus",
    "kingdom": "Animalia",
    "phylum": "Porifera",
    "class": "Demospongiae",
    "order": "Suberitida",
    "family": "Suberitidae",
    "genus": "Aaptos",
    "valid_AphiaID": 132064,
    "valid_name": "Aaptos",
    "match_type": "exact",
    "lsid": "urn:lsid:marinespecies.org:taxname:132064",
}

AAPTOS_ROW = {"sampleID": "S1", "featureID": "f1", "count": "3", "taxonomy": "g__Aaptos;s__Aaptos"}


def worms_handler(request: httpx.Request) -> httpx.Response:
    if "AphiaRecordsByMatchNames" in str(request.url):
        n = str(request.url).count("scientificnames")
        return httpx.Response(200, json=[[AAPTOS_RECORD] for _ in range(n)])
    if "AphiaRecordByAphiaID/132064" in str(request.url):
        return httpx.Response(200, json=AAPTOS_RECORD)
    return httpx.Response(404)


def registers_answering(
    handler: Callable[[httpx.Request], httpx.Response], cache_dir: Path | None = None
) -> OpenRegisters:
    return register_clients(cache_dir, client=httpx.Client(transport=httpx.MockTransport(handler)))


def write_intermediate(rows: list[dict[str, str]]) -> None:
    write_tsv(rows, artifacts.INTERMEDIATE)


@pytest.fixture
def mock_registers(monkeypatch, tmp_path) -> Path:
    cache_root = tmp_path / "cache"
    monkeypatch.setattr(
        "edna2dwc.cli.taxonomy.platformdirs.user_cache_dir", lambda name: str(cache_root)
    )
    monkeypatch.setattr(
        "edna2dwc.cli.taxonomy.register_clients",
        lambda cache_dir: registers_answering(worms_handler, cache_dir),
    )
    return cache_root


@pytest.fixture
def conversion_dir(tmp_path, monkeypatch) -> Path:
    directory = tmp_path / "conversion"
    directory.mkdir()
    monkeypatch.chdir(directory)
    artifacts.ANSWERS.write_text(
        answers.skeleton(
            dataset_id="test-dataset",
            created="2026-10-08T00:00:00Z",
            out_dir=Path("archive"),
            harvested=Manifest(),
        ),
        encoding="utf-8",
    )
    set_taxonomy_policy(registers=["worms"])
    artifacts.CONFIG.write_text("steps: []\n", encoding="utf-8")
    write_intermediate([AAPTOS_ROW])
    return directory


def set_taxonomy_policy(**policy) -> None:
    raw = yaml.safe_load(artifacts.ANSWERS.read_text(encoding="utf-8"))
    raw["taxonomy"].update(policy)
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw), encoding="utf-8")
