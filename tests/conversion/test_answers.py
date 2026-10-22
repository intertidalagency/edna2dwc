from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from edna2dwc.conversion import answers
from edna2dwc.dwca.manifest import REQUIRED_METADATA, BoundingBox, Manifest, Person

REQUIRED = {"dataset_id": "survey-2025", "created": "2026-01-01T00:00:00Z", "out_dir": "archive"}


def _write(tmp_path: Path, **sections) -> Path:
    path = tmp_path / "answers.yaml"
    path.write_text(yaml.safe_dump({**REQUIRED, **sections}), encoding="utf-8")
    return path


def test_the_required_fields_alone_load_with_every_default(tmp_path):
    loaded = answers.load(_write(tmp_path))
    assert loaded.dataset_id == "survey-2025"
    assert loaded.out_dir == Path("archive")
    assert loaded.taxonomy == answers.TaxonomySettings()
    assert loaded.taxonomy.registers == ("worms", "gbif")
    assert loaded.markers == {}
    assert loaded.blank_metadata() == list(REQUIRED_METADATA)


@pytest.mark.parametrize("missing", ["dataset_id", "created", "out_dir"])
def test_a_missing_required_field_is_named(tmp_path, missing):
    path = tmp_path / "answers.yaml"
    path.write_text(yaml.safe_dump({k: v for k, v in REQUIRED.items() if k != missing}))
    with pytest.raises(answers.AnswersError, match=missing):
        answers.load(path)


@pytest.mark.parametrize(
    "out_dir",
    [
        ".",
        "..",
        "confirmed",
        "proposed",
        "./sub/..",
        "../sibling",
        "archive/../../sibling",
        "proposed/archive",
        "confirmed/archive",
        "Confirmed",
        "PROPOSED/archive",
    ],
)
def test_an_out_dir_build_could_not_empty_safely_is_refused(tmp_path, out_dir):
    with pytest.raises(answers.AnswersError, match="out_dir"):
        answers.load(_write(tmp_path, out_dir=out_dir))


def test_an_absolute_out_dir_is_refused_even_inside_the_conversion(tmp_path):
    with pytest.raises(answers.AnswersError, match="out_dir"):
        answers.load(_write(tmp_path, out_dir=str(tmp_path / "archive")))


def test_an_out_dir_reached_through_a_symbolic_link_out_of_the_conversion_is_refused(tmp_path):
    conversion = tmp_path / "conversion"
    conversion.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (conversion / "archive").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(answers.AnswersError, match="out_dir"):
        answers.load(_write(conversion, out_dir="archive"))


def test_a_missing_file_says_to_run_init(tmp_path):
    with pytest.raises(answers.AnswersError, match="edna2dwc init"):
        answers.load(tmp_path / "answers.yaml")


def test_an_unknown_top_level_key_is_named(tmp_path):
    with pytest.raises(answers.AnswersError, match="environment"):
        answers.load(_write(tmp_path, environment={"constants": {}}))


def test_an_unknown_key_inside_a_section_is_named_with_its_section(tmp_path):
    with pytest.raises(answers.AnswersError, match=r"filters\.exclude_humans"):
        answers.load(_write(tmp_path, filters={"exclude_humans": True}))


def test_an_excluded_kingdom_is_matched_whatever_its_case(tmp_path):
    loaded = answers.load(_write(tmp_path, filters={"exclude_kingdoms": ["bacteria", "VIRUSES"]}))
    assert loaded.filters.exclude_kingdoms == ["Bacteria", "Viruses"]


def test_an_unknown_excluded_kingdom_is_refused(tmp_path):
    with pytest.raises(answers.AnswersError, match="Bacterium"):
        answers.load(_write(tmp_path, filters={"exclude_kingdoms": ["Bacterium"]}))


@pytest.mark.parametrize(
    ("sections", "named"),
    [
        ({"metadata": {"title": {"value": "Kelp", "provenance": ""}}}, r"metadata\.title"),
        ({"markers": {"12S": {"target": "vertebrates"}}}, r"markers\.12S.*provenance"),
        (
            {"markers": {"12S": {"target": "vertebrates", "justification": "methods.pdf"}}},
            r"markers\.12S.*provenance",
        ),
        (
            {
                "markers": {
                    "16S": {
                        "target": "bacteria",
                        "provenance": "16S V4 primers",
                        "constants": {"sop": {"value": "protocol A"}},
                    }
                }
            },
            r"markers\.16S\.constants\.sop",
        ),
        ({"controls": {"NC05": {"value": "sample"}}}, r"controls\.NC05 needs provenance"),
        ({"constants": {"samplingProtocol": {"value": "1 L"}}}, r"constants\.samplingProtocol"),
        ({"units": {"conductivity": {"value": "mS/cm"}}}, r"units\.conductivity"),
        (
            {"term_states": {"impossible": {"recordedBy": "never recorded"}}},
            r"term_states\.impossible\.recordedBy.*provenance",
        ),
        ({"adjudications": {"ON_LAND": {"status": "accepted"}}}, "ON_LAND.*provenance"),
        (
            {
                "adjudications": {
                    "ON_LAND": {
                        "status": "accepted",
                        "cause": "intertidal sites",
                        "provenance": "PI",
                    }
                }
            },
            "ON_LAND.*provenance",
        ),
    ],
)
def test_an_answer_without_provenance_is_refused_naming_its_key(tmp_path, sections, named):
    with pytest.raises(answers.AnswersError, match=named):
        answers.load(_write(tmp_path, **sections))


def test_a_blank_metadata_value_counts_as_unanswered(tmp_path):
    loaded = answers.load(_write(tmp_path, metadata={"title": {"value": "", "provenance": ""}}))
    assert "title" in loaded.blank_metadata()


def test_a_metadata_value_is_loaded_with_its_provenance_and_confirmation(tmp_path):
    entry = {"value": "Kelp", "provenance": "the PI", "confirmed": "PI: yes, that title"}
    loaded = answers.load(_write(tmp_path, metadata={"title": entry}))
    assert loaded.metadata.values["title"] == "Kelp"
    assert loaded.metadata.provenance["title"] == "the PI"
    assert loaded.metadata.confirmed["title"] == "PI: yes, that title"
    assert loaded.unconfirmed == []


def _skeleton(harvested: Manifest | None = None) -> str:
    return answers.skeleton(
        dataset_id="survey-2025",
        created="2026-01-01T00:00:00Z",
        out_dir=Path("archive"),
        harvested=harvested or Manifest(),
    )


def _metadata(tmp_path: Path, name: str, value, **entry) -> answers.Answers:
    return answers.load(
        _write(tmp_path, metadata={name: {"value": value, "provenance": "PI", **entry}})
    )


def test_a_methods_description_loads_for_the_eml_methods(tmp_path):
    loaded = _metadata(tmp_path, "methods_description", "Filtered 1 L of seawater")
    assert loaded.metadata.values["methods_description"] == "Filtered 1 L of seawater"


def test_every_unconfirmed_answer_is_named_by_its_key(tmp_path):
    chosen = {"value": "x", "provenance": "no source gave one"}
    loaded = answers.load(
        _write(
            tmp_path,
            metadata={"pub_date": {"value": "2026", "provenance": "the build year"}},
            markers={
                "12S": {
                    "target": "vertebrates",
                    "provenance": "MiFish primers",
                    "constants": {"sop": chosen},
                }
            },
            controls={"NC05": {"value": "sample", "provenance": "a site name"}},
            filters={"exclude_human": {"value": False, "provenance": "the study surveys fish"}},
            adjudications={"ON_LAND": {"status": "accepted", "provenance": "intertidal sites"}},
            constants={
                "samplingProtocol": chosen,
                "seq_meth": {"value": "x", "provenance": "PI"},
            },
            units={"conductivity": {"value": "mS/cm", "provenance": "usual unit"}},
            term_states={"impossible": {"annealingTemp": {"provenance": "no PCR profile given"}}},
        )
    )
    assert sorted(loaded.unconfirmed) == [
        "adjudications.ON_LAND",
        "constants.samplingProtocol",
        "constants.seq_meth",
        "controls.NC05",
        "filters.exclude_human",
        "markers.12S",
        "markers.12S.constants.sop",
        "metadata.pub_date",
        "term_states.impossible.annealingTemp",
        "units.conductivity",
    ]


def test_a_term_state_reason_loads_its_provenance(tmp_path):
    reason = {"provenance": "never recorded", "confirmed": "PI"}
    loaded = answers.load(_write(tmp_path, term_states={"impossible": {"recordedBy": reason}}))
    assert loaded.term_states.impossible == {"recordedBy": "never recorded"}
    assert loaded.unconfirmed == []


def test_exclude_human_takes_a_value_with_provenance_and_a_confirmation(tmp_path):
    answer = {"value": False, "provenance": "the study targets fish", "confirmed": "PI: publish"}
    loaded = answers.load(_write(tmp_path, filters={"exclude_human": answer}))
    assert loaded.filters.exclude_human is False
    assert loaded.unconfirmed == []


def test_exclude_human_is_unanswered_while_null(tmp_path):
    loaded = answers.load(_write(tmp_path, filters={"exclude_human": None}))
    assert loaded.filters.exclude_human is None


@pytest.mark.parametrize(
    "answer", [{"value": "no", "provenance": "PI"}, {"value": True}, "yes", True, False]
)
def test_an_exclude_human_answer_that_is_not_a_flag_with_provenance_is_refused(tmp_path, answer):
    with pytest.raises(answers.AnswersError, match=r"filters\.exclude_human"):
        answers.load(_write(tmp_path, filters={"exclude_human": answer}))


def test_people_load_as_a_list_of_people(tmp_path):
    loaded = _metadata(
        tmp_path,
        "creators",
        [
            {
                "given": "Jane",
                "surname": "Doe",
                "organization": "Example Foundation",
                "email": "jane.doe@example.com",
                "orcid": "0000-0002-1825-0097",
            },
            {"organization": "Example Institute"},
        ],
    )
    assert loaded.metadata.people["creators"] == [
        Person(
            given="Jane",
            surname="Doe",
            organization="Example Foundation",
            email="jane.doe@example.com",
            orcid="0000-0002-1825-0097",
        ),
        Person(organization="Example Institute"),
    ]
    assert "creators" not in loaded.blank_metadata()


def test_people_written_as_one_string_are_refused(tmp_path):
    with pytest.raises(answers.AnswersError, match=r"metadata\.creators\.value must be a list"):
        _metadata(tmp_path, "creators", "Smith, J.; Doe, A.")


def test_a_person_needs_a_surname_or_an_organization(tmp_path):
    with pytest.raises(answers.AnswersError, match=r"metadata\.contacts\.value\[0\]"):
        _metadata(tmp_path, "contacts", [{"given": "Jane", "email": "jane@example.com"}])


def test_an_unknown_key_on_a_person_is_named(tmp_path):
    with pytest.raises(answers.AnswersError, match=r"metadata\.creators\.value\[0\]\.name"):
        _metadata(tmp_path, "creators", [{"name": "Jane Doe"}])


def test_a_comma_in_an_unquoted_value_is_named_with_the_fix(tmp_path):
    people = yaml.safe_load(
        "[{given: Ana, organization: Fisheries Dept, Bureau of Marine Fisheries}]"
    )
    with pytest.raises(answers.AnswersError, match="put a value that holds a comma in quotes"):
        _metadata(tmp_path, "creators", people)


def test_the_skeletons_person_example_loads_with_its_comma(tmp_path):
    skeleton = _skeleton()
    lines = skeleton.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("#   - {given:"))
    example = " ".join(line.removeprefix("#") for line in lines[start : start + 2])
    (person,) = yaml.safe_load(example)
    assert "," in person["organization"]
    assert _metadata(tmp_path, "creators", [person]).metadata


def test_an_orcid_must_be_the_bare_identifier(tmp_path):
    with pytest.raises(answers.AnswersError, match="orcid"):
        _metadata(
            tmp_path, "creators", [{"surname": "Lopez", "orcid": "https://orcid.org/0000-0002"}]
        )


def test_a_bounding_box_loads_by_name(tmp_path):
    loaded = _metadata(
        tmp_path, "bounding_box", {"west": -123.14, "south": 49.26, "east": -123.1, "north": 49.28}
    )
    assert loaded.metadata.bounding_box == BoundingBox(
        west=-123.14, south=49.26, east=-123.1, north=49.28
    )


def test_a_bounding_box_written_as_a_list_is_refused(tmp_path):
    with pytest.raises(answers.AnswersError, match="west, south, east, north"):
        _metadata(tmp_path, "bounding_box", "-123.14,49.26,-123.1,49.28")


@pytest.mark.parametrize(
    "box, problem",
    [
        ({"west": -123.1, "south": 49.2, "east": -123.0}, "north"),
        ({"west": -123.1, "south": 49.2, "east": -123.0, "north": "49.3N"}, "north"),
        ({"west": -123.1, "south": 49.2, "east": -123.0, "north": 91}, "north"),
        ({"west": -190, "south": 49.2, "east": -123.0, "north": 49.3}, "west"),
        ({"west": -123.1, "south": 49.3, "east": -123.0, "north": 49.2}, "south"),
    ],
)
def test_an_implausible_bounding_box_is_refused_naming_the_coordinate(tmp_path, box, problem):
    with pytest.raises(answers.AnswersError, match=problem):
        _metadata(tmp_path, "bounding_box", box)


def test_a_box_crossing_the_antimeridian_is_accepted(tmp_path):
    loaded = _metadata(
        tmp_path, "bounding_box", {"west": 170, "south": -20, "east": -170, "north": -10}
    )
    assert loaded.metadata.bounding_box == BoundingBox(west=170, south=-20, east=-170, north=-10)


@pytest.mark.parametrize("name", ["title", "creators", "abstract", "geographic_description"])
def test_any_field_may_be_blank_when_its_provenance_says_why(tmp_path, name):
    loaded = _metadata(tmp_path, name, "")
    assert loaded.metadata.provenance[name] == "PI"
    assert name not in loaded.blank_metadata()
    assert not loaded.metadata.is_set(name)


def test_adjudications_are_a_section_keyed_by_issue_class(tmp_path):
    accepted = {"status": "accepted", "provenance": "intertidal sites", "confirmed": "PI: yes"}
    loaded = answers.load(_write(tmp_path, adjudications={"ON_LAND": accepted}))
    assert loaded.adjudications == {"ON_LAND": "accepted"}
    assert loaded.unconfirmed == []


def test_an_adjudication_nobody_confirmed_is_named_for_review(tmp_path):
    accepted = {"status": "accepted", "provenance": "the habitat column says intertidal"}
    loaded = answers.load(_write(tmp_path, adjudications={"ON_LAND": accepted}))
    assert loaded.unconfirmed == ["adjudications.ON_LAND"]
    assert loaded.adjudications == {}


def test_adjudications_naming_a_file_are_refused_with_the_shape_to_use(tmp_path):
    with pytest.raises(answers.AnswersError, match="ON_LAND: {status: accepted"):
        answers.load(_write(tmp_path, adjudications="adjudications.yaml"))


def test_a_license_gbif_cannot_read_is_refused(tmp_path):
    with pytest.raises(answers.AnswersError, match="CC0-1.0, CC-BY-4.0, CC-BY-NC-4.0"):
        _metadata(tmp_path, "license", "Non-commercial use with credit to the author")


def test_a_pending_status_is_refused_as_an_unknown_key(tmp_path):
    with pytest.raises(answers.AnswersError, match=r"metadata\.title.*status"):
        _metadata(tmp_path, "title", "Kelp", status="pending")


def test_a_marker_answer_keeps_its_provenance(tmp_path):
    entry = {"target": "prokaryotes", "provenance": "methods.pdf (515F/806R primers)"}
    loaded = answers.load(_write(tmp_path, markers={"16S": entry}))
    assert loaded.markers["16S"].provenance == "methods.pdf (515F/806R primers)"
    assert loaded.unconfirmed == ["markers.16S"]


def test_the_skeletons_marker_example_loads(tmp_path):
    skeleton = _skeleton()
    example = next(line for line in skeleton.splitlines() if line.startswith("#   MiFish-U:"))
    markers = yaml.safe_load(example.removeprefix("#"))
    assert answers.load(_write(tmp_path, markers=markers)).markers["MiFish-U"].target == (
        "vertebrates"
    )


def test_a_marker_target_outside_the_vocabulary_is_refused(tmp_path):
    with pytest.raises(answers.AnswersError, match="fish"):
        answers.load(
            _write(tmp_path, markers={"12S": {"target": "fish", "provenance": "primers"}})
        )


PROKARYOTES_515F = answers.MarkerTarget("prokaryotes", "515F")


@pytest.mark.parametrize(
    ("markers", "present", "targets"),
    [
        (["16S"], {""}, {"": PROKARYOTES_515F}),
        (["16S"], {"COI"}, {}),
        (["16S", "18S"], {""}, {}),
        (["16S"], {"16S", ""}, {"16S": PROKARYOTES_515F}),
    ],
)
def test_an_unmarked_table_reads_its_target_only_from_a_lone_entry(
    tmp_path, markers, present, targets
):
    entry = {"target": "prokaryotes", "provenance": "515F"}
    loaded = answers.load(_write(tmp_path, markers=dict.fromkeys(markers, entry)))
    assert loaded.marker_targets(present) == targets


def test_a_control_answer_must_be_control_or_sample(tmp_path):
    with pytest.raises(answers.AnswersError, match=r"controls\.NC05\.value"):
        answers.load(_write(tmp_path, controls={"NC05": {"value": "blank", "provenance": "PI"}}))


@pytest.mark.parametrize("value", [None, ""])
def test_a_constant_without_a_value_is_refused(tmp_path, value):
    constant = {"samplingProtocol": {"value": value, "provenance": "PI"}}
    with pytest.raises(answers.AnswersError, match=r"constants\.samplingProtocol needs a value"):
        answers.load(_write(tmp_path, constants=constant))


def test_an_unknown_key_in_an_answer_is_named(tmp_path):
    control = {"NC05": {"value": "sample", "provenance": "PI", "status": "pending"}}
    with pytest.raises(answers.AnswersError, match=r"controls\.NC05.*status"):
        answers.load(_write(tmp_path, controls=control))


def test_a_control_answer_loads_as_its_value(tmp_path):
    loaded = answers.load(
        _write(tmp_path, controls={"NC05": {"value": "sample", "provenance": "PI"}})
    )
    assert loaded.controls == {"NC05": "sample"}


def test_a_constant_on_a_term_the_taxonomy_writes_is_refused(tmp_path):
    with pytest.raises(answers.AnswersError, match=r"constants\.phylum.*confirmed/taxa\.tsv"):
        answers.load(
            _write(tmp_path, constants={"phylum": {"value": "Chordata", "provenance": "PI"}})
        )


def test_a_marker_constant_on_a_term_the_taxonomy_writes_is_refused(tmp_path):
    marker = {"target": "vertebrates", "provenance": "MiFish-U primers"}
    marker["constants"] = {"kingdom": {"value": "Animalia", "provenance": "PI"}}
    with pytest.raises(answers.AnswersError, match=r"markers\.12S\.constants\.kingdom"):
        answers.load(_write(tmp_path, markers={"12S": marker}))


@pytest.mark.parametrize(
    ("column", "unit"), [("conductivity", "mS/cm"), ("temp_C", "degrees Fahrenheit")]
)
def test_a_unit_answer_loads_as_its_value_whatever_its_header_says(tmp_path, column, unit):
    units = {column: {"value": unit, "provenance": "methods.pdf"}}
    assert answers.load(_write(tmp_path, units=units)).units == {column: (unit, "methods.pdf")}


@pytest.mark.parametrize(
    "filters", [{"sample_type_col": "type"}, {"sample_metadata": "samples.tsv"}]
)
def test_a_sample_type_column_and_a_sample_metadata_file_are_refused_alone(tmp_path, filters):
    (tmp_path / "samples.tsv").write_text("sampleID\ttype\n", encoding="utf-8")
    with pytest.raises(answers.AnswersError) as refused:
        answers.load(_write(tmp_path, filters=filters))
    assert "filters.sample_type_col" in str(refused.value)
    assert "filters.sample_metadata" in str(refused.value)


def test_absences_need_a_targeted_assay(tmp_path):
    with pytest.raises(answers.AnswersError, match="targeted_assay"):
        answers.load(_write(tmp_path, derive_fields={"emit_absences": True}))


def test_a_taxonomy_flag_must_be_a_boolean(tmp_path):
    with pytest.raises(answers.AnswersError, match=r"taxonomy\.marine_only"):
        answers.load(_write(tmp_path, taxonomy={"marine_only": "no"}))


def test_registers_are_tried_in_the_order_given(tmp_path):
    loaded = answers.load(_write(tmp_path, taxonomy={"registers": ["gbif", "worms"]}))
    assert loaded.taxonomy.registers == ("gbif", "worms")


@pytest.mark.parametrize("registers", [[], ["worms", "worms"], ["ncbi"], "worms"])
def test_registers_must_list_known_registers_once_each(tmp_path, registers):
    with pytest.raises(answers.AnswersError, match=r"taxonomy\.registers"):
        answers.load(_write(tmp_path, taxonomy={"registers": registers}))


_PROKARYOTES = {"target": "prokaryotes", "provenance": "515F/806R"}


def test_a_marker_overrides_the_dataset_taxonomy_settings_it_names(tmp_path):
    loaded = answers.load(
        _write(
            tmp_path,
            taxonomy={"marine_only": True},
            markers={
                "16S": {
                    **_PROKARYOTES,
                    "taxonomy": {"registers": ["worms"], "require_confident": True},
                },
                "12S": {"target": "vertebrates", "provenance": "MiFish"},
            },
        )
    )
    scopes = loaded.taxonomy_scopes({"16S", "12S"})
    assert scopes == {"16S": "16S"}
    assert loaded.taxonomy_for(scopes["16S"]) == answers.TaxonomySettings(
        registers=("worms",), marine_only=True, require_confident=True
    )
    assert loaded.taxonomy_for(scopes.get("12S", "")) == loaded.taxonomy


def test_a_marker_taxonomy_setting_is_checked_like_a_dataset_one(tmp_path):
    with pytest.raises(answers.AnswersError, match=r"markers\.16S\.taxonomy\.marine"):
        answers.load(
            _write(tmp_path, markers={"16S": {**_PROKARYOTES, "taxonomy": {"marine": True}}})
        )


def test_taxonomy_settings_describe_every_setting():
    described = answers.TaxonomySettings(registers=("gbif",)).describe()
    assert described.startswith("registers: gbif; marine_only: false")


@pytest.mark.parametrize(
    ("answer", "kingdoms"),
    [
        ("prokaryotes", {"Bacteria", "Archaea"}),
        ("vertebrates", {"Animalia"}),
        ("bacteria, fungi", {"Bacteria", "Fungi"}),
    ],
)
def test_a_marker_target_names_the_kingdoms_it_amplifies(answer, kingdoms):
    assert answers.target_kingdoms(answer) == kingdoms


def test_the_skeleton_loads_and_keeps_harvested_metadata(tmp_path):
    harvested = Manifest()
    harvested.set("title", "Kelp: a survey", provenance="eml.xml title")
    path = tmp_path / "answers.yaml"
    path.write_text(_skeleton(harvested))
    assert yaml.safe_load(path.read_text())["metadata"]["version"] == 1
    loaded = answers.load(path)
    assert loaded.metadata.values == {"title": "Kelp: a survey"}
    assert loaded.metadata.provenance == {"title": "eml.xml title"}
    assert loaded.unconfirmed == ["metadata.title"]


def test_the_metadata_version_loads_as_an_integer(tmp_path):
    assert answers.load(_write(tmp_path, metadata={"version": 2})).metadata.version == 2
    assert answers.load(_write(tmp_path)).metadata.version == 1


@pytest.mark.parametrize("version", [0, -1, 1.5, "2", True])
def test_a_version_that_is_not_a_positive_integer_is_refused(tmp_path, version):
    with pytest.raises(answers.AnswersError, match=r"metadata\.version"):
        answers.load(_write(tmp_path, metadata={"version": version}))


def test_the_skeleton_keeps_harvested_people_and_bounding_box(tmp_path):
    harvested = Manifest()
    people = [Person(given="Jane", surname="Doe"), Person(organization="Example Institute")]
    box = BoundingBox(west=-123.14, south=49.26, east=-123.1, north=49.28)
    harvested.set_people("contacts", people, provenance="contacts")
    harvested.set_bounding_box(box, provenance="bounding_box")
    path = tmp_path / "answers.yaml"
    path.write_text(_skeleton(harvested))
    loaded = answers.load(path)
    assert loaded.metadata.people == {"contacts": people}
    assert loaded.metadata.bounding_box == box


@pytest.mark.parametrize(
    ("dataset_id", "expected"),
    [
        ("", "blank"),
        ("   ", "blank"),
        ("my:survey", "colon"),
        ("my\tsurvey", "tab"),
        ("my\nsurvey", "newline"),
        ("my\rsurvey", "carriage return"),
    ],
)
def test_a_dataset_id_that_cannot_key_an_occurrence_is_rejected(dataset_id, expected):
    with pytest.raises(answers.DatasetIdError, match=expected):
        answers.validate_dataset_id(dataset_id)


def test_a_marker_takes_taxon_exclusions_with_their_provenance(tmp_path):
    marker = {
        "target": "eukaryotes",
        "provenance": "18S V9 primers",
        "exclude_taxa": {"value": ["Metazoa", "Streptophyta"], "provenance": "paper.pdf"},
    }
    loaded = answers.load(_write(tmp_path, markers={"18S": marker}))
    assert loaded.markers["18S"].exclude_taxa == ("Metazoa", "Streptophyta")


def test_taxon_exclusions_must_be_a_list_of_names(tmp_path):
    marker = {
        "target": "eukaryotes",
        "provenance": "18S V9 primers",
        "exclude_taxa": {"value": "Metazoa", "provenance": "paper.pdf"},
    }
    with pytest.raises(answers.AnswersError, match="exclude_taxa"):
        answers.load(_write(tmp_path, markers={"18S": marker}))


def test_build_switches_load_from_the_build_key(tmp_path):
    loaded = answers.load(_write(tmp_path, build={"no_dna_extension": True, "no_emof": True}))
    assert (loaded.build.no_dna_extension, loaded.build.no_emof) == (True, True)


def test_a_setting_written_as_an_answer_is_refused_with_the_plain_shape(tmp_path):
    answer = {"value": "tables/samples.csv", "provenance": "p", "confirmed": ""}
    with pytest.raises(answers.AnswersError, match="setting, not an answer") as refused:
        answers.load(_write(tmp_path, filters={"sample_metadata": answer}))
    assert "sample_metadata: tables/samples.csv" in str(refused.value)


@pytest.mark.parametrize(
    ("section", "name"),
    [
        ("filters", "sample_type_col"),
        ("filters", "occurrence_type_col"),
        ("derive_fields", "timestamp_col_a"),
        ("derive_fields", "timestamp_col_b"),
    ],
)
def test_a_column_setting_that_is_not_text_is_refused(tmp_path, section, name):
    with pytest.raises(answers.AnswersError, match=f"{section}.{name} must be text"):
        answers.load(_write(tmp_path, **{section: {name: ["x"]}}))


def test_a_sample_metadata_file_that_does_not_exist_is_refused_at_load(tmp_path):
    with pytest.raises(answers.AnswersError, match="not a file"):
        answers.load(
            _write(
                tmp_path,
                filters={"sample_metadata": "tables/samples.csv", "sample_type_col": "type"},
            )
        )


def test_sample_metadata_needs_its_type_column(tmp_path):
    (tmp_path / "samples.csv").write_text("sampleID,type\n")
    with pytest.raises(answers.AnswersError, match="sample_type_col"):
        answers.load(_write(tmp_path, filters={"sample_metadata": "samples.csv"}))


def test_sample_metadata_loads_relative_to_the_answers_file(tmp_path):
    (tmp_path / "samples.csv").write_text("sampleID,type\n")
    loaded = answers.load(
        _write(tmp_path, filters={"sample_metadata": "samples.csv", "sample_type_col": "type"})
    )
    assert (loaded.filters.sample_metadata, loaded.filters.sample_type_col) == (
        Path("samples.csv"),
        "type",
    )


SHAPES = [
    None,
    "",
    "x",
    0,
    1,
    True,
    [],
    ["x"],
    [{"value": "x"}],
    [["x"]],
    {},
    {"value": "x"},
    {"value": "x", "provenance": "p", "confirmed": ""},
    {"provenance": "p"},
    {"value": {"value": "x"}},
]


def _key_paths(node: object, prefix: tuple = ()) -> list[tuple]:
    if not isinstance(node, dict):
        return [prefix] if prefix else []
    return [prefix] * bool(prefix) + [
        path for key, value in node.items() for path in _key_paths(value, (*prefix, key))
    ]


def _with(node: dict, path: tuple, shape: object) -> dict:
    copied = dict(node)
    *head, last = path
    target = copied
    for key in head:
        target[key] = dict(target[key])
        target = target[key]
    target[last] = shape
    return copied


def test_no_shape_in_any_key_raises_anything_but_a_named_answers_error(tmp_path):
    skeleton = yaml.safe_load(_skeleton())
    path = tmp_path / "answers.yaml"
    escaped = []
    for key_path in _key_paths(skeleton):
        for shape in SHAPES:
            path.write_text(yaml.safe_dump(_with(skeleton, key_path, shape)), encoding="utf-8")
            try:
                answers.load(path)
            except answers.AnswersError:
                continue
            except Exception as error:  # noqa: BLE001
                escaped.append((".".join(key_path), shape, f"{type(error).__name__}: {error}"))
    assert escaped == []


def test_a_confirmation_no_person_wrote_is_refused_with_its_key(tmp_path):
    path = _write(
        tmp_path,
        metadata={"title": {"value": "Kelp", "provenance": "eml.xml", "confirmed": "automatic"}},
    )
    with pytest.raises(answers.AnswersError, match="metadata.title"):
        answers.load(path)


@pytest.mark.parametrize("term", ["eventID", "occurrenceID", "materialSampleID", "taxonID"])
def test_a_constant_for_a_term_that_identifies_one_record_is_refused(tmp_path, term):
    path = _write(tmp_path, constants={term: {"value": "E1", "provenance": "a test"}})
    with pytest.raises(answers.AnswersError, match=f"constants.{term}"):
        answers.load(path)


def test_a_marker_written_with_value_is_told_to_write_target(tmp_path):
    path = _write(tmp_path, markers={"12S": {"value": "vertebrates", "provenance": "a test"}})
    with pytest.raises(answers.AnswersError, match=r"markers take target:, not value:"):
        answers.load(path)
