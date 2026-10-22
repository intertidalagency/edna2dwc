# Third-party notices

`edna2dwc` is MIT licensed. It bundles the data and schemas below, which keep their own terms.

| What | Where | Source | Terms |
| --- | --- | --- | --- |
| Darwin Core term list | `edna2dwc/terms/dwc_terms.json` | [TDWG Darwin Core](https://github.com/tdwg/dwc), `dist/simple_dwc_vertical.csv` and `vocabulary/term_versions.csv` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), Biodiversity Information Standards (TDWG) |
| DNA derived data and ExtendedMeasurementOrFact extension terms | `edna2dwc/terms/dwc_terms.json` | [GBIF registered extensions](https://rs.gbif.org/extensions.html): `gbif/1.0/dna_derived_data_2022-02-23.xml` and `obis/extended_measurement_or_fact.xml` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), per [GBIF's terms of use](https://www.gbif.org/terms) |
| Country boundaries | `edna2dwc/data/boundaries.json.gz` | [Natural Earth](https://www.naturalearthdata.com/) 1:10m Admin 0 Countries, version 5.1.2, simplified by `maintenance/boundaries.py` | Public domain |
| ISO 3166-1 alpha-2 codes | `edna2dwc/data/iso3166_alpha2.txt` | The assigned codes, as listed by ISO | Facts, no copyright claimed |
| GBIF metadata profile schema | `edna2dwc/data/eml-xsd/eml-gbif-profile.xsd`, `gbif-xml.xsd`, `dc.xsd` | [rs.gbif.org/schema/eml-gbif-profile/1.2](https://rs.gbif.org/schema/eml-gbif-profile/1.2/eml.xsd), fetched by `maintenance/eml_schema.py` | Per [GBIF's terms of use](https://www.gbif.org/terms). Used by the test suite only; in the repository, not in the wheel or source distribution |
| Ecological Metadata Language 2.1.1 schema | `edna2dwc/data/eml-xsd/eml.xsd` | [NCEAS EML](https://github.com/NCEAS/eml) | [GPL-2.0](https://github.com/NCEAS/eml/blob/main/LICENSE). Used by the test suite only; in the repository, not in the wheel or source distribution |
| W3C `xml.xsd` | `edna2dwc/data/eml-xsd/w3-xml.xsd`, `w3-xml-2009.xsd` | [W3C](https://www.w3.org/2001/xml.xsd) | [W3C Software and Document License](https://www.w3.org/copyright/software-license/) |

`edna2dwc terms sync` regenerates the term list and `maintenance/` holds the scripts that regenerate the boundaries and schemas; each records its source URL.

At run time, `resolve-taxonomy` queries [WoRMS](https://www.marinespecies.org/) and the [GBIF Backbone Taxonomy](https://www.gbif.org/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c), and `evaluate` sends the archive to [GBIF's validator](https://www.gbif.org/tools/data-validator). Nothing from them is bundled. Their terms apply to the records they return, and a published dataset should cite them.
