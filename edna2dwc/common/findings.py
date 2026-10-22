from __future__ import annotations


ERROR = "error"
WARNING = "warning"
INFO = "info"
_SEVERITIES = frozenset({ERROR, WARNING, INFO})

_TABLE: dict[str, tuple[str, str]] = {
    "CONTRACT_TYPE_INVALID": (ERROR, "count is non-numeric or negative"),
    "PRESENCE_ONLY_FILTERED": (
        INFO,
    ),
        INFO,
        (
    "TAXON_FUZZY": (WARNING, "Non-confident match retained"),
    "TAXON_REJECTED_ORGANELLE": (INFO, "Candidate rejected as organellar"),
    "SOURCE_KINGDOM_UNINFORMATIVE": (
        WARNING,
        (
            "Source lineage is domain-level only, so the kingdom check cannot discriminate; "
            "non-confident matches refused dataset-wide"
        ),
    ),
    "TAXON_ID_CONTRADICTS_SOURCE": (
    ),
    "CONTROL_TAXON_LEAKAGE": (
        WARNING,
        "A positive-control organism appears in a non-control sample",
    ),
    "COORDINATE_SIGN_SUSPECT": (
    ),
    "TIMESTAMP_CONFLICT": (
    ),
    "TAXON_AMBIGUOUS_HOMONYM": (WARNING, "≥2 exact accepted candidates, tiebreak failed"),
    "TAXON_HOMONYM_DISAMBIGUATED": (
        INFO,
        "≥2 exact accepted candidates, tiebreak broke the tie using phylum/class",
    ),
    "TAXON_LABEL_STALE": (INFO, "Label refreshed from the register"),
    "CONTROL_EXCLUDED": (INFO, "A control/blank sample was removed"),
    "CONTAMINANT_EXCLUDED": (INFO, "A taxon-level exclusion was applied"),
    "DECISION_REQUIRED": (
        ERROR,
    ),
    "MAPPING_ROW_MISSING": (
        WARNING,
        (
        ),
    ),
    "DYNAMIC_PROPERTIES_KEY_COLLISION": (
        WARNING,
        "An unmapped column shares a key with an existing dynamicProperties blob on a row",
    ),
    "DYNAMIC_PROPERTIES_MALFORMED": (
        WARNING,
    ),
    "CONSTANT_OVERWROTE_MAPPED_VALUE": (
    ),
    "EMOF_TYPE_UNVOCABULARIED": (
        INFO,
        "eMoF row emitted with free-text type; no controlled-vocabulary URI",
    ),
    "GBIF_VALIDATOR_UNAVAILABLE": (
        WARNING,
    ),
    "TERM_AMBIGUOUS": (
    ),
    "TERM_TARGET_COLLISION": (
        WARNING,
        "Two source columns proposed the same DwC term; the weaker match was rerouted for review",
    ),
    "TERM_NOT_DARWIN_CORE": (
        ERROR,
    ),
    "TERM_MISSING_RECOMMENDED": (WARNING, "A recommended-tier term is absent"),
        WARNING,
    ),
    "TERM_FORMAT_INVALID": (ERROR, "A value violates its required format"),
    "TERM_FORMAT_UNCONVERTIBLE": (
        WARNING,
    ),
    "TERM_PAIR_INCOMPLETE": (
        ERROR,
        (
        ),
    ),
    "META_INDEX_MISMATCH": (ERROR, "meta.xml <field> index ≠ header position"),
    "ARCHIVE_INVALID": (ERROR, "Structural validation failed"),
    "ROW_ACCOUNTING_MISMATCH": (
        ERROR,
        (
            "Intermediate row count != archive rows + documented exclusions; a record left "
            "the pipeline with no disclosure"
        ),
    ),
    "GBIF_VALIDATOR_ISSUE": (
        ERROR,
        "Reported by the GBIF validation API; severity mirrors GBIF's",
    ),
    "OBIS_VALIDATOR_ISSUE": (ERROR, "Reported by the OBIS QC rule set"),
    "STRUCTURAL_COST_DISCLOSED": (
        INFO,
        (
        ),
    ),
    "SCRIPT_MISSING": (ERROR, "A script named in steps: is absent from scripts/"),
    "ENVIRONMENT_UNAVAILABLE": (
        WARNING,
        (
            "A recorded package version could not be installed; replay stopped. Run with "
            "--unpin to use current package versions instead (not a perfect replay)"
        ),
    ),
}

VARIABLE_SEVERITY_CODES = frozenset(
)

CODES = frozenset(_TABLE)


def default_severity(code: str) -> str:
    return _TABLE[code][0]


def meaning(code: str) -> str:
    return _TABLE[code][1]


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    count: int = 1
    detail_file: str | None = None

    def to_dict(self) -> dict:
        d = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "count": self.count,
        }
        if self.detail_file is not None:
            d["detail_file"] = self.detail_file
        return d


def new_finding(
    code: str,
    message: str,
    *,
    severity: str | None = None,
    count: int = 1,
    detail_file: str | None = None,
) -> Finding:
    if code not in CODES:
        raise ValueError(f"{code!r} is not in the closed finding-code vocabulary")
    if severity is None:
        if code in VARIABLE_SEVERITY_CODES:
        severity = default_severity(code)
    elif severity not in _SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(_SEVERITIES)}, got {severity!r}")
    return Finding(
        code=code, severity=severity, message=message, count=count, detail_file=detail_file
    )


@dataclass
class FindingsLog:
    findings: list[Finding] = field(default_factory=list)

    def add(self, code: str, message: str, **kwargs) -> Finding:
        finding = new_finding(code, message, **kwargs)
        self.findings.append(finding)
        return finding

    def has_errors(self) -> bool:
        return any(f.severity == ERROR for f in self.findings)

    def to_list(self) -> list[dict]:
        return [f.to_dict() for f in self.findings]
