from __future__ import annotations

from dataclasses import dataclass, field, replace

ERROR = "error"
WARNING = "warning"
INFO = "info"
_SEVERITIES = frozenset({ERROR, WARNING, INFO})

_TABLE: dict[str, tuple[str, str]] = {
    "CONTRACT_INVALID": (ERROR, "occurrence_long.tsv violates the intermediate table's schema"),
    "CONTRACT_COLUMN_MISSING": (ERROR, "A required occurrence_long.tsv column is absent"),
    "CONTRACT_COLUMN_RESERVED": (
        ERROR,
        "occurrence_long.tsv has a column resolve-taxonomy writes, so its values would be lost",
    ),
    "CONTRACT_TYPE_INVALID": (ERROR, "count is non-numeric or negative"),
    "TAXONOMY_BLANK": (
        WARNING,
        "No row of occurrence_long.tsv has a lineage, so every occurrence would be the placeholder taxon Biota incertae sedis",
    ),
    "ZERO_COUNTS_KEPT": (
        ERROR,
        (
            "Rows left after the exclusions have zero counts and derive_fields.emit_absences "
            "is not set; run assemble without --keep-zeros, or publish them as absences"
        ),
    ),
    "INPUT_TOTALS": (INFO, "An input's rows and count total, as assemble read it"),
    "JOIN_UNMATCHED": (
        WARNING,
        "Rows of a features, sequences or samples table whose key matches no count row",
    ),
    "JOIN_METADATA_MISSING": (
        WARNING,
        (
            "Count rows whose key has no row in a features, sequences or samples table, so "
            "they are published with blank columns from it; count is how many keys"
        ),
    ),
    "PRESENCE_ONLY_FILTERED": (
        INFO,
        "Zero counts assemble dropped by the presence-only default; count is how many",
    ),
    "SAMPLE_SIZE_AFTER_EXCLUSIONS": (
        INFO,
        (
            "A library lost reads to an exclusion, so its sampleSizeValue counts the reads "
            "published, not the reads sequenced"
        ),
    ),
    "SAMPLE_SIZE_PER_MARKER": (
        INFO,
        (
            "sampleSizeValue was summed per (sampleID, marker) because a sampleID has "
            "more than one marker; count is how many such sampleIDs"
        ),
    ),
    "SAMPLE_SIZE_UNGROUPED": (
        INFO,
        (
            "The table has no marker column, so sampleSizeValue is a per-sampleID sum; a "
            "merged multi-marker table would inflate every denominator"
        ),
    ),
    "SAMPLE_SIZE_SUPPLIED": (
        INFO,
        "A supplied sampleSizeValue was kept rather than overwritten; count is how many rows",
    ),
    "SAMPLE_SIZE_DISAGREEMENT": (
        WARNING,
        (
            "Rows of one sequencing library ship different sampleSizeValues, so a reader "
            "computing a relative abundance gets a different answer per row; count is how "
            "many libraries"
        ),
    ),
    "MARKER_INCOMPLETE": (
        WARNING,
        (
            "Some rows have a marker and others leave it blank, so the blank-marker rows are "
            "grouped as a separate library; count is how many rows"
        ),
    ),
    "COUNTRY_CODE_CONTRADICTS_COORDINATES": (
        WARNING,
        (
            "A countryCode from the source names a different country from the one the "
            "boundary set places its coordinates in, and was kept as given; count is how many rows"
        ),
    ),
    "COUNTRY_CODE_FROM_NEARBY_COAST": (
        WARNING,
        (
            "Coordinates in no country's land polygon took the countryCode of the nearest "
            "country, within 25 km of its coast; count is how many rows"
        ),
    ),
    "GEOGRAPHIC_COVERAGE_DERIVED": (
        INFO,
        (
            "metadata.bounding_box is not given, so eml.xml's geographic coverage is the "
            "smallest box around the published coordinates"
        ),
    ),
    "TAXON_UNRESOLVED": (
        WARNING,
        "No name in the lineage that could be looked up matched; placeholder taxon used",
    ),
    "TAXON_FUZZY": (WARNING, "Non-confident match retained"),
    "TAXON_MASS_COLLAPSE": (
        WARNING,
        (
            "Five or more differently named lineages resolved to one taxon that none of their "
            "source lineages names, which usually means the names were misread"
        ),
    ),
    "TAXON_RANK_WORD_REFUSED": (
        WARNING,
        "A source name was a bare rank word such as Genus, so it was never looked up",
    ),
    "TAXON_FUZZY_REJECTED": (WARNING, "Non-confident match refused; resolution backed off"),
    "TAXON_REJECTED_KINGDOM": (
        INFO,
        "Candidate's kingdom group, or domain if confident, contradicts the source's",
    ),
    "TAXON_REJECTED_ORGANELLE": (INFO, "Candidate rejected as organellar"),
    "SOURCE_KINGDOM_UNINFORMATIVE": (
        WARNING,
        (
            "Source lineage is domain-level only, so the kingdom check cannot discriminate; "
            "non-confident matches refused dataset-wide"
        ),
    ),
    "NCBI_TAXID_MALFORMED": (
        WARNING,
        (
            "An ncbi_taxid is malformed or names no taxon (0, 1 for the root, 131567 for "
            "cellular organisms), so it was not published"
        ),
    ),
    "TAXON_ID_UNCHECKED": (
        WARNING,
        (
            "WoRMS didn't answer when a register ID already in the source was checked against "
            "its name; the source ID is kept unchecked and its row is up for review in taxa.tsv. "
            "Run resolve-taxonomy again to check it"
        ),
    ),
    "TAXON_ID_CONTRADICTS_SOURCE": (
        WARNING,
        (
            "Name-based resolution disagrees with a register ID already in the source; the "
            "source ID is kept and its row is up for review in taxa.tsv"
        ),
    ),
    "CONTROL_TAXON_LEAKAGE": (
        WARNING,
        "A positive-control organism appears in a non-control sample",
    ),
    "COORDINATE_SIGN_SUSPECT": (
        WARNING,
        (
            "A few rows' coordinate signs contradict the rest of the dataset; the values are "
            "kept as given, proposed/derived_values.tsv waits for a correction, and a person "
            "judges the signs under adjudications:"
        ),
    ),
    "TIMESTAMP_CONFLICT": (
        WARNING,
        (
            "Two source date/time columns disagree on the same row; verbatimEventDate keeps "
            "both, and a person judges which is right under adjudications:"
        ),
    ),
    "TAXON_ID_BLANK": (
        WARNING,
        (
            "A row has no DNA sequence to hash, or one that is not DNA, so its taxonID and "
            "DNA_sequence are blank; count is how many rows"
        ),
    ),
    "SEQUENCE_COLUMNS_DISAGREE": (
        WARNING,
        (
            "Two sequence columns give a row different sequences; the one mapped to "
            "DNA_sequence is published and hashed; count is how many rows"
        ),
    ),
    "FEATURE_ID_NOT_SEQUENCE_HASH": (
        WARNING,
        (
            "A featureID shaped like an MD5 hash is not the MD5 of its row's sequence, so "
            "taxonID was built from the sequence; count is how many rows"
        ),
    ),
    "TAXON_AMBIGUOUS_HOMONYM": (WARNING, "≥2 exact accepted candidates, tiebreak failed"),
    "TAXON_HOMONYM_DISAMBIGUATED": (
        INFO,
        "≥2 exact accepted candidates, tiebreak broke the tie using phylum/class",
    ),
    "TAXON_LABEL_STALE": (INFO, "Label refreshed from the register"),
    "TAXON_LABEL_REFRESH_INCOMPLETE": (
        WARNING,
        (
            "The register stopped answering during the label refresh, so the resolved names "
            "are whatever resolution itself settled on; rerun resolve-taxonomy"
        ),
    ),
    "CONTROL_EXCLUDED": (INFO, "A control/blank sample was removed"),
    "CONTROL_AMBIGUOUS": (
        WARNING,
        "Keyword match not corroborated by metadata; build halts until answers.yaml's controls answers it",
    ),
    "CONTROL_ANSWER_UNMATCHED": (
        ERROR,
        (
            "A sampleID under controls: in answers.yaml is not in the table, so its answer "
            "settles nothing; the build stops until it is removed or corrected"
        ),
    ),
    "CONTAMINANT_EXCLUDED": (INFO, "A taxon-level exclusion was applied"),
    "HUMAN_EXCLUDED": (
        INFO,
        "A human (Homo) row was removed, as filters.exclude_human: true asks",
    ),
    "HUMAN_PUBLISHED": (
        WARNING,
        (
            "Human (Homo) rows were published, as filters.exclude_human: false asks; count is "
            "how many rows, and the message says whether a person confirmed the answer"
        ),
    ),
    "DECISION_REQUIRED": (
        ERROR,
        "answers.yaml lacks an answer only a person can give; sets status: needs_decision",
    ),
    "TERM_UNMAPPED": (
        WARNING,
        "Column mapped to no named term; build keeps it in dynamicProperties",
    ),
    "MAPPING_ROW_MISSING": (
        WARNING,
        (
            "A column in the data has no row in proposed/term_mapping.tsv, so it was routed to "
            "dynamicProperties like an unmapped column: the column reached the table after "
            "the mapping was proposed and names no term outright"
        ),
    ),
    "DERIVED_VALUE_REPLACED": (
        INFO,
        (
            "A value in a row of confirmed/derived_values.tsv replaced the value derived for "
            "that row, and the values derived from it follow"
        ),
    ),
    "DERIVED_CONFIRMED_UNMATCHED": (
        ERROR,
        (
            "A row of confirmed/derived_values.tsv matches no row of the table build "
            "derived values for, so it settles nothing; the build stops until it is removed "
            "or corrected"
        ),
    ),
    "DYNAMIC_PROPERTIES_KEY_COLLISION": (
        WARNING,
        "An unmapped column shares a key with an existing dynamicProperties blob on a row",
    ),
    "DYNAMIC_PROPERTIES_MALFORMED": (
        WARNING,
        "An existing dynamicProperties value is not valid JSON, not a JSON object, or names a key twice; ignored",
    ),
    "CONSTANT_OVERWROTE_MAPPED_VALUE": (
        ERROR,
        "A constant would replace a value the data gives for the same term; sets status: error",
    ),
    "MEASUREMENT_UNIT_OVERRIDDEN": (
        INFO,
        "A units: answer replaced the unit a measurement column's header or values name",
    ),
    "MEASUREMENT_UNITS_MIXED": (
        ERROR,
        "A measurement column's values state a unit other than its header names, or units its units: answer would publish as one",
    ),
    "EMOF_TYPE_UNVOCABULARIED": (
        INFO,
        "eMoF row emitted with free-text type; no controlled-vocabulary URI",
    ),
    "DNA_TERMS_ROUTED": (
        INFO,
        (
            "DNADerivedData-classed columns moved out of the core into the dnaderiveddata "
            "extension, or core rows that had no such value; count is how many"
        ),
    ),
    "DNA_TERMS_IN_CORE": (
        WARNING,
        (
            "The archive's core table has DNADerivedData-classed columns that belong in "
            "the dnaderiveddata extension"
        ),
    ),
    "GBIF_VALIDATOR_UNAVAILABLE": (
        WARNING,
        "GBIF's validation API could not be reached; validation not measured this run",
    ),
    "GBIF_CREDENTIALS_MISSING": (
        WARNING,
        "No GBIF account is configured anywhere; GBIF validation not measured this run",
    ),
    "GBIF_CREDENTIALS_PARTIAL": (
        WARNING,
        (
            "A GBIF account is half-configured (one of the two environment variables, or a "
            "username with no password in any source), so none of it was used"
        ),
    ),
    "GBIF_CREDENTIALS_UNREADABLE": (
        WARNING,
        "A credentials file exists but this process cannot trust or parse it",
    ),
    "GBIF_CREDENTIALS_REJECTED": (
        WARNING,
        "GBIF rejected the configured account (HTTP 401); GBIF validation not measured",
    ),
    "TERM_AMBIGUOUS": (
        WARNING,
        (
            "≥2 plausible DwC terms for a source column; it goes to dynamicProperties until a "
            "row in confirmed/term_mapping.tsv names its term"
        ),
    ),
    "TERM_TARGET_COLLISION": (
        WARNING,
        "Two source columns proposed the same DwC term; the weaker match was rerouted for review",
    ),
    "TERM_NOT_DARWIN_CORE": (
        ERROR,
        "A mapped column or a constant names no Darwin Core or extension term, so the build stops",
    ),
    "TERM_MISSING_RECOMMENDED": (WARNING, "A recommended-tier term is absent"),
    "TERM_MISSING_PRIORITY": (
        WARNING,
        "A priority eDNA term rated required or strongly recommended is absent",
    ),
    "TERM_FORMAT_INVALID": (ERROR, "A value violates its required format"),
    "TERM_FORMAT_UNCONVERTIBLE": (
        WARNING,
        "Could not convert to the required format, so the value was left blank",
    ),
    "TERM_PAIR_INCOMPLETE": (
        ERROR,
        (
            "One term of a required pair is present without the other, reported once per pair "
            "and file; count is how many rows. Severity varies by pair"
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
    "ADJUDICATION_NEEDED": (
        ERROR,
        (
            "A finding only a person can judge: a validator issue such as OBIS ON_LAND for "
            "shoreline sampling, or a finding that changed or blanked published values. "
            "build waits on it in review, even under --automatic, until adjudications: in "
            "answers.yaml accepts its code or the data changes"
        ),
    ),
    "STRUCTURAL_COST_DISCLOSED": (
        INFO,
        (
            "A finding or validator issue class a person accepted under adjudications: in "
            "answers.yaml, so the archive ships as it is; not counted against the validator "
            "checks"
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
    "PROPOSAL_OPEN": (
        ERROR,
        (
            "A proposal has something to review and no sheet in confirmed/; sets status: "
            "needs_review"
        ),
    ),
    "UNCONFIRMED_ACCEPTED": (
        INFO,
        "An answer with confirmed: empty was used under --automatic without a person confirming it",
    ),
    "PROPOSAL_ACCEPTED": (
        INFO,
        "A proposal with something to review was used as written, under --automatic",
    ),
    "CONFIRMED_SHEET_APPLIED": (
        INFO,
        "A sheet in confirmed/ was applied over the tool's proposal",
    ),
    "CONFIRMED_ROW_UNMATCHED": (
        ERROR,
        (
            "A row of a sheet in confirmed/ names a key the proposal no longer has, so it "
            "settles nothing; the build stops until it is removed or corrected"
        ),
    ),
    "TAXON_NOT_FROM_LOCK": (
        ERROR,
        (
            "A row publishes a scientificName and scientificNameID pair that no row of "
            "resolved_taxonomy.tsv or confirmed/taxa.tsv gives; sets status: error"
        ),
    ),
    "TAXON_OVERRIDDEN": (
        INFO,
        "A row of confirmed/taxa.tsv replaced the resolved_taxonomy.tsv row with the same lineage_key",
    ),
    "TAXON_OVERRIDE_INCONSISTENT": (
        ERROR,
        (
            "A row of confirmed/taxa.tsv changes scientificName but keeps the old name's "
            "scientificNameID, authorship or rank, so it was not applied"
        ),
    ),
    "RUN_FAILED": (ERROR, "A packaging step reported an error; sets status: error"),
    "BUNDLE_SCRIPT_NOT_RUN": (
        INFO,
        (
            "A file in scripts/ is bundled, but no step in conversion.yaml runs it. Delete it "
            "unless a reader script imports it"
        ),
    ),
    "BUNDLE_ARTIFACT_MISSING": (
        ERROR,
        "An artifact that belongs in reproduce/ is absent; severity varies by whether a replay needs it",
    ),
    "TERM_STATE_MISSING": (
        WARNING,
        "A priority eDNA term reached term_states.tsv with no state; fails the every-term gate",
    ),
}

JUDGED_BY_A_PERSON = frozenset(
    {
        "JOIN_METADATA_MISSING",
        "TAXON_MASS_COLLAPSE",
        "TAXON_AMBIGUOUS_HOMONYM",
        "TERM_FORMAT_UNCONVERTIBLE",
        "COUNTRY_CODE_CONTRADICTS_COORDINATES",
        "SAMPLE_SIZE_DISAGREEMENT",
        "MARKER_INCOMPLETE",
        "SEQUENCE_COLUMNS_DISAGREE",
        "DYNAMIC_PROPERTIES_MALFORMED",
        "DYNAMIC_PROPERTIES_KEY_COLLISION",
        "TIMESTAMP_CONFLICT",
        "HUMAN_PUBLISHED",
        "COORDINATE_SIGN_SUSPECT",
    }
)

HALT_CODES = {
    "needs_decision": "DECISION_REQUIRED",
    "needs_review": "PROPOSAL_OPEN",
    "error": "RUN_FAILED",
}

VARIABLE_SEVERITY_CODES = frozenset(
    {
        "TERM_PAIR_INCOMPLETE",
        "GBIF_VALIDATOR_ISSUE",
        "OBIS_VALIDATOR_ISSUE",
        "BUNDLE_ARTIFACT_MISSING",
    }
)

CODES = frozenset(_TABLE)


def default_severity(code: str) -> str:
    return _TABLE[code][0]


def meaning(code: str) -> str:
    return _TABLE[code][1]


VARIES = "varies"


def severity_label(code: str) -> str:
    return VARIES if code in VARIABLE_SEVERITY_CODES else default_severity(code)


def reference_table() -> str:
    rows = []
    for code in sorted(CODES):
        escaped_meaning = meaning(code).replace("|", "\\|")
        rows.append(f"| `{code}` | {severity_label(code)} | {escaped_meaning} |")
    return "\n".join(["| Code | Severity | Meaning |", "| --- | --- | --- |", *rows])


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
            raise ValueError(f"{code!r} has no fixed severity: pass severity= explicitly")
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

    def merged(self) -> FindingsLog:
        counts: dict[Finding, int] = {}
        for finding in self.findings:
            key = replace(finding, count=1)
            counts[key] = counts.get(key, 0) + finding.count
        return FindingsLog([replace(finding, count=count) for finding, count in counts.items()])
