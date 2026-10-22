from __future__ import annotations

from pathlib import Path

import yaml

PROPOSED_DIR = Path("proposed")
CONFIRMED_DIR = Path("confirmed")
BUNDLE_DIR = Path("reproduce")
TABLES_DIR = Path("tables")

CONFIG = Path("conversion.yaml")
ANSWERS = Path("answers.yaml")

INTERMEDIATE = Path("occurrence_long.tsv")
RESOLVED_TAXONOMY = Path("resolved_taxonomy.tsv")
EXCLUDED_ROWS_REPORT = Path("excluded_rows_report.tsv")
MAPPING = Path("term_mapping.tsv")
TERM_STATES = Path("term_states.tsv")
FINDINGS = Path("findings.json")
AUDIT_RECORD = Path("audit_record.json")
ASSEMBLY = Path("assembly.json")
REVIEW_PAGE = Path("REVIEW.md")

ZIP_NAME = "dwca.zip"
REPORT_FILENAME = "CONVERSION_REPORT.md"
REPORT_PAGE_FILENAMES = (REPORT_FILENAME, "CONVERSION_REPORT.html")
REPORT_DATA_FILENAME = "CONVERSION_REPORT.json"


def read_recipe(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def write_recipe(config_path: Path, recipe: dict) -> None:
    config_path.write_text(yaml.safe_dump(recipe, sort_keys=False), encoding="utf-8")
