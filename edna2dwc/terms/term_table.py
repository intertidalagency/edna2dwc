from __future__ import annotations

import json
from pathlib import Path

PACKAGED_TERM_TABLE = Path(__file__).parent / "dwc_terms.json"


def load_term_table(path: Path | None = None) -> dict:
    return json.loads((path or PACKAGED_TERM_TABLE).read_text(encoding="utf-8"))
