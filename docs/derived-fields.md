# Derived fields

Some terms no column gives can be worked out from the rest of a row: a country from coordinates, a read total from the counts. This page lists what `build` derives, how to correct a derived value, and when an archive can publish absences.

## What `build` derives

`build` derives after it applies the term mapping, so each rule reads terms, never source column names, and fills a term only on a row the source left blank. A value the source gives, in a mapped column or as a constant, is kept, even one that can't be converted to its term's format and so is published blank. `build` derives these:

- **`countryCode`**, from the coordinates and a bundled land boundary set: Natural Earth 1:10m admin-0 countries, version 5.1.2, simplified to about 500 m. Enclaves such as Lesotho, San Marino and Vatican City are holes in the country around them. A point in no country's polygon, such as a water sample near shore, takes the code of the nearest country when that country's coastline is within 25 km, measured on the sphere, and across the antimeridian. One `COUNTRY_CODE_FROM_NEARBY_COAST` counts those rows and names some of them with their distance and code: check one that lies near a border or between two coasts. A point farther out gets a blank code, and one `TERM_MISSING_PRIORITY` counts those rows and names their coordinates. Coordinates are read from `decimalLatitude` and `decimalLongitude` as the term mapping, with `confirmed/term_mapping.tsv` over the proposal, fills them, so a swap confirmed there moves the code and the footprint too. Another `TERM_MISSING_PRIORITY` counts the rows with no coordinates, whose code is blank too. A row whose source gives a `countryCode`, in a column or as a constant in `answers.yaml`, keeps it, and when the coordinates fall inside another country's polygon, `COUNTRY_CODE_CONTRADICTS_COORDINATES` says so. A given code is never compared with the nearest country of a point at sea.
- **`organismQuantity`** and **`organismQuantityType`**: the `count` and what it measures. `count` is a number of `DNA sequence reads` unless `answers.yaml` gives `organismQuantityType` as a constant, dataset-wide or under a marker, such as `relative abundance` or `copies per liter`. A count that isn't a whole number can't be reads, so `build` stops and asks for that constant for its marker.
- **`sampleSizeValue`** and **`sampleSizeUnit`**: the total reads of the row's library, in `DNA sequence reads`. Only reads are summed: when `organismQuantityType` names anything else, such as relative abundance, `sampleSizeValue` stays blank unless the source gives it. A library is `(sampleID, marker)`, or `sampleID` when no row has a `marker`. A row with a `sampleSizeValue`, in the column the term mapping sends to it, keeps it with the unit from the column mapped to `sampleSizeUnit` (`SAMPLE_SIZE_SUPPLIED`), and never takes the reads unit. The total is taken after controls, human reads and excluded kingdoms are removed, so it counts the reads published, not the reads sequenced. When an exclusion lowered a library's total, `SAMPLE_SIZE_AFTER_EXCLUSIONS` gives both numbers.
- **`occurrenceStatus`**: `present` for a positive count. `build` refuses a table whose `count` is missing or not a finite number, such as `NaN` or `inf`, as `assemble` reports it. See [Absences](#absences) for zero counts.
- **`dataGeneralizations`**, on a record published at a coarser rank than its source named.
- **`maximumDepthInMeters`**: the depth mapped to `minimumDepthInMeters`, on a row with no maximum depth of its own or a blank one, whatever order the columns come in, since a single depth is both.
- **`footprintWKT`** and **`footprintSRS`**: `POINT (lon lat)` from the row's coordinates, unless the row has a footprint in the column the term mapping sends to `footprintWKT`. The row's published `geodeticDatum`, from a column mapped to it or a constant, becomes its `footprintSRS`, and a row with no `geodeticDatum` gets a point with no `footprintSRS`, just as its coordinates are published with no datum. A footprint from the source, such as a transect's `LINESTRING`, takes the row's `geodeticDatum` as its `footprintSRS` when it has none, and `TERM_PAIR_INCOMPLETE` reports one left without.
- **`verbatimEventDate`**: the source dates, when two timestamp columns disagree. Applying the term mapping also fills it when converting a date to `eventDate` changed the date's form, and when the date can't be converted, so the source value is never lost.

`basisOfRecord` is `MaterialSample` unless a column sets it. No other term gets a default. `geodeticDatum` comes only from the source, and coordinates without it draw a warning: GBIF then assumes WGS84 and flags the record `GEODETIC_DATUM_ASSUMED_WGS84`. `eventDate` keeps the time and the zone the source gave, and a time with no zone stays without one. Minutes without seconds, fractional seconds, `Z`, an offset such as `-08:00` and a space in place of the `T`, as in `2025-06-04 23:30`, are all accepted. An ambiguous date such as `06/05/2025` is never guessed: `eventDate` is left blank, the value goes to `verbatimEventDate`, and one `TERM_FORMAT_UNCONVERTIBLE` per term gives the count and examples.

These findings report on the read totals and coordinates:

| Finding | Meaning |
| --- | --- |
| `SAMPLE_SIZE_UNGROUPED` | No `marker` column, so a `sampleID` with several markers gets one total across them |
| `SAMPLE_SIZE_PER_MARKER` | The sampleIDs with more than one marker |
| `MARKER_INCOMPLETE` | Some rows leave `marker` blank while others set it |
| `SAMPLE_SIZE_DISAGREEMENT` | Rows of one library don't agree on `sampleSizeValue` |
| `TERM_PAIR_INCOMPLETE` | A `sampleSizeValue` with no `sampleSizeUnit`. Supply the unit in the source, in a column mapped to `sampleSizeUnit`. The build stops |
| `COORDINATE_SIGN_SUSPECT` | With at least 5 values on an axis, under 20% have the opposite sign. Puts `proposed/derived_values.tsv` up for review. The sign is never changed. It waits under `adjudications:` (see below) |
| `TIMESTAMP_CONFLICT` | `derive_fields.timestamp_col_a` and `timestamp_col_b` disagree on a row; both values are kept in `verbatimEventDate`. It waits under `adjudications:` (see below) |
| `TERM_FORMAT_UNCONVERTIBLE` | A value a mapped column gives can't be converted to its term's format, such as `1/20/2015` for `eventDate`, so it is left blank, with a date kept in `verbatimEventDate`. It waits under `adjudications:` (see below) |

## Findings a person judges

A finding that changes or blanks what the archive publishes is not closed by reading it. `build` raises `ADJUDICATION_NEEDED` for each one, lists it under "Waiting on you" in `REVIEW.md` with status `needs_review`, even under `--automatic`, and ships the archive only once `adjudications:` in `answers.yaml` accepts the code, with a person's reply in `confirmed`, or the data changes. An acceptance with `confirmed` empty doesn't count. These codes wait this way: `JOIN_METADATA_MISSING`, `TERM_FORMAT_UNCONVERTIBLE`, `TIMESTAMP_CONFLICT`, `HUMAN_PUBLISHED` unless a person confirmed `filters.exclude_human`, `COORDINATE_SIGN_SUSPECT`, `TAXON_MASS_COLLAPSE`, `TAXON_AMBIGUOUS_HOMONYM`, `COUNTRY_CODE_CONTRADICTS_COORDINATES`, `SAMPLE_SIZE_DISAGREEMENT`, `MARKER_INCOMPLETE`, `SEQUENCE_COLUMNS_DISAGREE`, `DYNAMIC_PROPERTIES_MALFORMED` and `DYNAMIC_PROPERTIES_KEY_COLLISION`, beside the validator issues such as OBIS `ON_LAND`. Accepting one says the archive is right as it is:

```yaml
adjudications:
  TERM_FORMAT_UNCONVERTIBLE: {status: accepted, provenance: "the dates are ambiguous day/month and stay in verbatimEventDate", confirmed: "J. Smith: leave eventDate blank"}
```

## Correcting a derived value

`proposed/derived_values.tsv` holds every row of the first 20 samples, as derived, with empty `provenance` and `confirmed` columns. Its columns are terms, beside `sampleID`, `featureID`, `count` and `marker`: a source column appears under the term it is mapped to, and one bound for `dynamicProperties` or eMoF doesn't appear. A row of `confirmed/derived_values.tsv` corrects the row with the same `(sampleID, featureID)`, in any sample, not only the first 20. Each cell that differs from the derived row is a correction, and an empty cell keeps the derived value. A row with a correction needs its `provenance`, saying what the correction rests on, or the build refuses the sheet and names the row. A row with `confirmed` empty holds the build for review until a person's reply is pasted there. Corrections to values the source gives, such as a coordinate or a count, are applied before the fields are derived, so `countryCode`, `footprintWKT` and `sampleSizeValue` follow them. A correction to a derived value, such as `countryCode`, replaces it. Both are reported as `DERIVED_VALUE_REPLACED`. A corrected value is converted to its term's format like any other. A confirmed row that matches nothing stops the build as `DERIVED_CONFIRMED_UNMATCHED`: remove it or correct its `sampleID` and `featureID`. A column the proposal doesn't have, such as a source column's own name, stops the build too, naming the term to use instead.

## Absences

By default the archive is presence-only: `assemble` drops zero counts, and `eml.xml` says so. A targeted assay with a recorded detection limit can publish zero counts as `occurrenceStatus="absent"`:

```yaml
derive_fields:
  emit_absences: true
term_states:
  assay_type: targeted_assay
constants:
  pcr_primer_lod:
    value: 3 copies per reaction
    provenance: "assay_validation.pdf p2"
    confirmed: ""
```

Keep the zeros with `edna2dwc assemble --keep-zeros`. `answers.yaml` fails to load with `emit_absences` unless both the assay type and the `pcr_primer_lod` constant are set. `build` then publishes zero counts as absent, and the `methods` section of `eml.xml` names the recorded limit. A metabarcoding archive can't publish absences, because a zero read count there isn't evidence of absence. Without `emit_absences`, `build` stops with `ZERO_COUNTS_KEPT` when a row left after the exclusions has a zero count. A zero in a control sample, a human read or another excluded row doesn't stop it.
