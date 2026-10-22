from __future__ import annotations

import json
from pathlib import Path

from edna2dwc.conversion import artifacts
from edna2dwc.reproduce import compare

AUDIT_RESULT_SCHEMA = '{"findings": ["occurrence.txt row 12: ..."]}'


def load_audit_result(path: Path) -> list[str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(_not_an_audit_result(path, f"it is not JSON: {error}")) from error
    findings = raw.get("findings") if isinstance(raw, dict) else None
    if not isinstance(findings, list) or not all(isinstance(f, str) for f in findings):
        raise ValueError(_not_an_audit_result(path, "'findings' must be a list of strings"))
    unknown_keys = sorted(set(raw) - {"findings"})
    if unknown_keys:
        named = ", ".join(repr(key) for key in unknown_keys)
        raise ValueError(_not_an_audit_result(path, f"it has keys other than 'findings': {named}"))
    return findings


def _not_an_audit_result(path: Path, reason: str) -> str:
    return (
        f"{path} is not an audit result: {reason}. Write one JSON object with a "
        f'"findings" list of sentences, empty if nothing turned up, such as {AUDIT_RESULT_SCHEMA}'
    )


def _archive_digest(archive_dir: Path | None) -> str:
    zip_path = archive_dir / artifacts.ZIP_NAME if archive_dir else None
    return compare.archive_digest(zip_path) if zip_path and zip_path.exists() else ""


def record_audit(
    record_path: Path, findings: list[str], *, archive_dir: Path | None = None
) -> None:
    record = {"findings": findings, "archive_sha256": _archive_digest(archive_dir)}
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def load_recorded_audit(
    record_path: Path, *, archive_dir: Path | None = None
) -> tuple[list[str], bool] | None:
    if not record_path.exists():
        return None
    record = json.loads(record_path.read_text(encoding="utf-8"))
    audited = record.get("archive_sha256", "")
    stale = not audited or audited != _archive_digest(archive_dir)
    return list(record["findings"]), stale


AUDIT_PROMPT_TEMPLATE = """\
You are conducting an independent fabrication audit of a Darwin Core Archive conversion. You have not seen how this archive was built and have no stake in it being correct. Your job is to find problems.

Inputs:
- Original source file(s): {source_paths}
- Finished archive directory: {archive_dir} (occurrence.txt, dnaderiveddata.txt and extendedmeasurementorfact.txt if present, meta.xml, eml.xml, and reproduce/answers.yaml and reproduce/resolved_taxonomy.tsv where the archive includes a reproduce bundle)
- To read a PDF, DOCX or XLSX, run `edna2dwc text <file>...`. It prints the text, and each sheet of a workbook as tab-separated rows. Don't write a parser.

A value is fabricated when it traces back to neither the source nor a declared register lookup. Taxonomic names, identifiers, authorships and ranks legitimately come from WoRMS or the GBIF backbone rather than from any source column, so an accepted-name substitution, a corrected higher rank, a scientificNameAuthorship, a taxonomicStatus, or the "Biota incertae sedis" placeholder standing in for an unassigned sequence is expected output, not invention. reproduce/resolved_taxonomy.tsv records the `authority` and the `resolution_path` behind every lineage, so check a taxonomic value against that file before calling it fabricated, and flag it only when that file does not account for it either.

Check specifically, and cite concrete evidence for every finding (don't just assert "looks fine" without saying what you checked):

1. Read eml.xml's title/abstract/creators/geographic coverage. For every specific claim (a number, a named person, a methodology detail, a place name), try to find matching evidence in the original source file(s) or the provenance: of a field in the metadata section of answers.yaml. Flag any specific claim you cannot trace to either.
2. Sample at least 10 rows from occurrence.txt (spread across the file, not just the first 10). For each: does occurrenceStatus match what organismQuantity/the read count implies (a zero count reported as "present" without explanation is a red flag)? Does decimalLatitude/decimalLongitude look like a plausible transform of any verbatim coordinate columns present in the same row? Does scientificName look consistent with any raw taxonomy/classification columns in the same row?
3. Check whether the provenance: of each field in answers.yaml's metadata section names where the value came from, and whether any field eml.xml uses has none. Provenance existing does not make it truthful, so spot-check a couple by opening the document or file it names and confirming it contains the claimed value.
4. For any field whose rendered text expands an abbreviation/acronym found in the source (a site code, a project shorthand) into full words, confirm the full form appears somewhere in a source document. If it does not, that is an undisclosed inference even when the expansion is plausible. Flag it even if the provenance tag looks correct otherwise (a real audit caught a tag that described a literal field copy when the rendered text had in fact silently expanded an acronym).
5. Open the source file(s) and list the data columns present there. For each, find where it ended up in the archive: a Darwin Core field, an extendedmeasurementorfact row, or inside dynamicProperties. Flag two things separately: (a) any source column you cannot find anywhere in the output at all, and (b) any column placed in a Darwin Core term that is not the most appropriate one for it, naming the term you would have used instead. A measurement placed in a dynamicProperties blob rather than an eMoF row counts as (b). A local file name or path, such as a FASTQ file's, and other pipeline bookkeeping that records how the data was processed rather than what was observed are expected to be dropped, so do not flag them under (a): raw reads belong in SRA or ENA, linked from the archive through associatedSequences.
6. Read every reader script in reproduce/scripts/ and the steps: in reproduce/conversion.yaml that run them. A reader script should only read the source files into tables. Flag any script that drops or filters rows, changes a value the source gives, writes a value no source gives, or decides what belongs in answers.yaml with its provenance: which samples are controls, which taxa a marker excludes, a constant, or a unit. Name the script, the line and what it does.

Report a list of specific, concrete findings (file, row or field, what looks wrong and why), or an empty `findings` list if nothing turned up after checking the above. Do not hedge everything as uncertain without having checked something specific.

Write the result to a file as one JSON object, which `edna2dwc audit record <archive> --from-file <file>` reads. findings lists each one as a sentence, and is empty when nothing turned up: {schema}
"""


def build_audit_prompt(*, source_paths: list[str], archive_dir: str) -> str:
    return AUDIT_PROMPT_TEMPLATE.format(
        source_paths=", ".join(source_paths), archive_dir=archive_dir, schema=AUDIT_RESULT_SCHEMA
    )
