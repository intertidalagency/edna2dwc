from xml.etree import ElementTree as ET

import pytest



def _full_manifest() -> Manifest:
    m = Manifest()
    )
    m.set(
        "geographic_description",
        "Monterey Bay, California",
    )
    return m




    )


def test_render_eml_xml_element_order_matches_the_schema_sequence():
        "title",
        "creator",
        "creator",
        "pubDate",
        "language",
        "abstract",
        "keywordSet",
        "intellectualRights",
        "coverage",
        "maintenance",
        "contact",
    ]


    assert description.text is None or not description.text.strip()








@pytest.mark.parametrize(
)
def test_render_eml_xml_raises_on_a_missing_required_field(missing_field):
    with pytest.raises(eml.EmlRenderError, match=missing_field):


    assert root.find(".//temporalCoverage") is None
    assert root.find(".//taxonomicCoverage") is None
    assert root.find("dataset/methods") is None


    )
    assert [c.tag for c in coverage] == [
        "geographicCoverage",
        "temporalCoverage",
        "taxonomicCoverage",
    ]


def test_render_eml_xml_omits_geographic_coverage_without_a_description():
    m = _full_manifest()
    m.values.pop("geographic_description")


def test_render_eml_xml_omits_coverage_entirely_with_no_real_data_at_all():
    m.values.pop("geographic_description")


def test_render_eml_xml_additional_metadata_is_a_sibling_of_dataset():
    assert [c.tag for c in root] == ["dataset", "additionalMetadata"]




