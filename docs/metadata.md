# Dataset metadata

The `metadata:` section of `answers.yaml` describes the dataset: its title, creators, abstract, license, contacts, publication date and the rest. `build` writes it into the archive's `eml.xml`. `init --scan` copies what it can from an `eml.xml` that came with the data. A person, or an agent working from the source documents, fills in the rest, and each value says what it rests on.

## Provenance and confirmation

Every answer in `answers.yaml`, in every section, is `{value, provenance, confirmed}`. `build` refuses to load an answer without `provenance`. A setting, which says how the tool runs rather than what is true of the data, is a plain value: `out_dir`, the `taxonomy:` block, `filters.exclude_kingdoms`, `filters.sample_metadata` and the column names under `filters:` and `derive_fields:`, `metadata.version`, `term_states.assay_type` and the `build:` block. A setting written as an answer, or a setting of the wrong type, fails when the file loads, and the message says what to write. `filters.sample_metadata` must name a file under the conversion directory, and needs `filters.sample_type_col` beside it.

- `provenance` says what the value rests on: the document and where in it, the data it was read from, or why it was chosen.
- `confirmed` is a person's reply, pasted as they gave it, or empty. Only a person's words go there. An agent never writes it. Leaving it out is the same as leaving it empty. A reply that is only a word no person would sign, such as `automatic`, `agent`, `data`, `yes` or `ok`, is refused when the file loads, and a confirmed sheet row with one refuses the sheet: with nobody to ask, leave `confirmed` empty and run `build --automatic`.

```yaml
metadata:
  title: {value: "Puget Sound eDNA survey 2026", provenance: "eml.xml title", confirmed: "J. Smith: yes"}
  license: {value: "", provenance: "waiting on the provider's choice", confirmed: ""}
```

A marker keeps `target` as its value key, an adjudication keeps `status`, and a term-state reason has no value: `{provenance, confirmed}`. `init --scan` writes each field it copies from an `eml.xml` with `provenance: "eml.xml <field>"` and `confirmed: ""`, so a person confirms each once.

Every answer whose `confirmed` is empty holds the build at `needs_review`. The archive is still built. `REVIEW.md` lists these answers by section. To close one, ask the researcher, paste their reply into `confirmed`, and build again. `build --automatic` uses each one as written, logs one `UNCONFIRMED_ACCEPTED` naming them, and lists them in `REVIEW.md` under "Accepted by --automatic, confirm". Use it when there is nobody to ask.

A required field (`title`, `creators`, `abstract`, `license`, `contacts`, `pub_date`) may be left blank with `provenance` saying what it waits on, as `license` is above. `build` writes the archive without it, reports the missing `eml.xml` element for any but `license`, and holds at `needs_review`, even with `--automatic`, because a blank can't be accepted. `pub_date` and `license` are often decided at publication. A required field that is blank with no `provenance` is unanswered, and `build` stops before writing the archive.

The conversion report lists each metadata field's `provenance`, and either the person's reply or "not confirmed by a person".

## What `eml.xml` holds

`build` stops if `answers.yaml` lacks a title, a creator, an abstract, a license, a contact or a publication date. It never fills them in. Any of them left blank with a `provenance` is left out of `eml.xml`, and the archive stays in review until it is set. GBIF's EML profile requires a title, a creator, a publication date, an abstract and a contact, so `REVIEW.md` and the report name each of those `eml.xml` lacks: the archive can't be published until they are set.

`license` is one of the three licenses GBIF accepts, `CC0-1.0`, `CC-BY-4.0` or `CC-BY-NC-4.0`, written into `intellectualRights` in the machine-readable form GBIF parses. `pub_date` is `YYYY` or `YYYY-MM-DD`.

`creators` and `contacts` are lists of people. Each person needs a `surname` or an `organization`, and may add `given`, `email` and `orcid`, the bare identifier. Quote a value that holds a comma: unquoted inside `{...}`, YAML reads the text after the comma as a new key. `bounding_box` names its sides in decimal degrees:

```yaml
metadata:
  creators:
    value:
      - {given: Ana, surname: Lopez, organization: "Example Institute, Marine Lab", email: ana.lopez@example.com, orcid: 0000-0002-1825-0097}
      - {organization: Example Foundation}
    provenance: "methods.pdf p2"
    confirmed: "J. Smith: yes"
  bounding_box:
    value: {west: -123.3, south: 49.2, east: -123.0, north: 49.4}
    provenance: "range of decimalLatitude and decimalLongitude in the data"
    confirmed: ""
```

- Each person is a `creator` or `contact` with `individualName` (`givenName`, `surName`), `organizationName`, `electronicMailAddress` and an ORCID `userId`, each written only when given.
- A bounding box with a longitude outside ±180, a latitude outside ±90, or a south above north fails when `answers.yaml` loads. A west east of east is accepted, for a box that crosses the antimeridian.
- Geographic coverage is `geographic_description` with `bounding_box`. Without `bounding_box`, it is the smallest box around the published `decimalLatitude` and `decimalLongitude`, and its description adds a sentence saying so. `GEOGRAPHIC_COVERAGE_DERIVED` reports the box. A `bounding_box` without a description, or no box and no coordinates, leaves geographic coverage out.
- Temporal coverage is the `eventDate` range. Taxonomic coverage is the distinct `kingdom` values without the placeholder taxon. Each is left out when the data doesn't support it.
- `methods` is the metadata's `methods_description`, then a sentence on the `occurrenceStatus` convention: presence-only, or absences with the recorded detection limit. A last step names what was excluded before publishing: controls, human reads and excluded taxa.
- `project` is optional, for a project and its funding that a source names. It needs a `title` and `personnel`, each person with a `role`, and may add `funding`, written as `<project>` with `<funding>`. A project without a title or personnel fails when `answers.yaml` loads; `build` never fills them from the dataset's own title or creators. The GBIF EML profile has no place for funding outside `<project>`, so funding a source names without a project can't be published. Leave `project` out rather than invent a title for it.
- `packageId` is `<dataset_id>/v<version>`, from `metadata.version` in `answers.yaml`: a bare whole number, not a value with provenance. `init` writes `version: 1`. Raise it by one each time you republish a corrected archive, so a register can tell the versions apart.
- Element order follows the bundled GBIF-profile XSD.
