

def test_find_schema_locations_extracts_every_reference():
    text = (
        '<xs:import schemaLocation="eml-gbif-profile.xsd"/>'
        '<xs:import schemaLocation="http://www.w3.org/2001/xml.xsd"/>'
    )
    assert find_schema_locations(text) == [
        "eml-gbif-profile.xsd",
        "http://www.w3.org/2001/xml.xsd",
    ]


def test_find_schema_locations_returns_empty_list_when_none_present():
    assert find_schema_locations("<xs:schema/>") == []


def test_rewrite_schema_locations_points_a_relative_reference_at_itself():
    text = '<xs:import schemaLocation="eml-gbif-profile.xsd"/>'
    rewritten = rewrite_schema_locations(text, ["eml-gbif-profile.xsd"])


def test_rewrite_schema_locations_rewrites_a_known_absolute_url():
    text = '<xs:import schemaLocation="http://www.w3.org/2001/xml.xsd"/>'
    rewritten = rewrite_schema_locations(text, ["http://www.w3.org/2001/xml.xsd"])
    assert rewritten == '<xs:import schemaLocation="w3-xml.xsd"/>'


def test_rewrite_schema_locations_uses_the_basename_for_an_unmapped_absolute_url():
    text = '<xs:import schemaLocation="http://example.com/unmapped.xsd"/>'
    rewritten = rewrite_schema_locations(text, ["http://example.com/unmapped.xsd"])
    assert rewritten == '<xs:import schemaLocation="unmapped.xsd"/>'
