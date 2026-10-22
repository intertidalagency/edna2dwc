from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "edna2dwc"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
INPUT_FIXTURES = FIXTURES_DIR / "inputs"
OCCURRENCE_LONG_FIXTURES = FIXTURES_DIR / "occurrence_long"
