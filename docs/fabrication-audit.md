# The fabrication audit

The tool can't reliably check its own output, so the last step of a conversion is an audit by a reviewer that didn't build the archive. The audit is a judgment, and it informs a person. It never changes the build's status or exit code.

```bash
edna2dwc audit prompt archive/ --source data/samples.xlsx --source data/methods.pdf
edna2dwc audit record archive/ --from-file audit_result.json
```

`audit prompt` prints the prompt for a fresh agent, with paths filled in. It tells the agent to read documents and workbooks with `edna2dwc text`. The agent sees only the source files and the finished archive, including `reproduce/resolved_taxonomy.tsv`, and none of the reasoning behind it. Give it the prompt unchanged. An agent passes it most reliably as a file: write the output to `AUDIT_PROMPT.md` and tell the auditor to read that file. A summary of your own decisions defeats the point.

The prompt asks the agent to trace each claim in `eml.xml` to a source or to its field's `provenance` in `answers.yaml`, check at least ten occurrence rows, open a few documents a `provenance` names to check they hold the value, confirm expanded acronyms, and find every source column in the output. It also asks it to read every recorded reader script and report one that filters rows or makes a decision that belongs in `answers.yaml`. A value counts as fabricated only if neither the sources nor `resolved_taxonomy.tsv` explain it. Accepted names, corrected ranks, authorship and the placeholder taxon all come from a register, not a source column.

The prompt asks the reviewer for one JSON object, `{"findings": ["..."]}`, with an empty list when nothing turned up, and `audit record` refuses anything else. Run `audit record` in the conversion directory. It stores the findings in `audit_record.json` beside `answers.yaml`, with the digest of the `dwca.zip` they were made against, rewrites `CONVERSION_REPORT.md` to list each finding in the auditor's words, and puts the record in `reproduce/`, so the archive needs no rebuild. Any later `build` does the same. `evaluate` lists the findings in `EVALUATION.md`. A build that changes the archive leaves the findings listed but says they were recorded against an earlier build, so a fixed problem doesn't read as open and a new one isn't assumed caught: audit again.

Audit once, after the last build that changes values, and record the findings as they are. Whether to fix one is the researcher's call: the reviewer can be wrong.
