from __future__ import annotations

import json
from pathlib import Path







        return None


AUDIT_PROMPT_TEMPLATE = """\

Inputs:
- Original source file(s): {source_paths}



"""


def build_audit_prompt(*, source_paths: list[str], archive_dir: str) -> str:
    return AUDIT_PROMPT_TEMPLATE.format(
    )
