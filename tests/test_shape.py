"""Markup, references, and WO 97's standard description taken apart.

The descriptions below are copied from Discovery's WO 97 entries as they read
on 2026-10-11, with their references.
"""

from __future__ import annotations

import pytest

from tna_discovery_mcp.shape import (
    as_department,
    as_id,
    as_reference,
    as_series,
    clean,
    entity_lines,
    is_wo97_item,
    level_of,
    name_matches,
    parse_wo97,
    place_matches,
    record_url,
    regiment_matches,
)

from .conftest import fixture


# --------------------------------------------------------------------------- #
# Markup
# --------------------------------------------------------------------------- #
def test_an_item_description_becomes_lines():
    raw = fixture("details_C8853102.json")["scopeContent"]["description"]
    assert clean(raw) == (
        "JOHN ATKINSON\nBorn MANCHESTER, Lancashire\nServed in Royal Artillery\nDischarged aged 41"
    )
    assert clean(raw, one_line=True) == (
        "JOHN ATKINSON Born MANCHESTER, Lancashire Served in Royal Artillery Discharged aged 41"
    )


def test_a_title_with_a_broken_entity_is_cleaned():
    raw = fixture("children_C14305_wo97.json")["assets"][0]["title"]
    assert raw.startswith("<unittitle type=&#34Title")
    assert clean(raw) == (
        "1760-1854: discharge papers arranged by regiment, but each described at item "
        "level. (WO 97/1-1271)"
    )


def test_markup_with_no_spaces_between_tags_still_separates_words():
    raw = fixture("details_D651997_digitised.json")["scopeContent"]["description"]
    assert clean(raw) == "W Josia Hargreaves"


def test_no_space_is_left_before_punctuation():
    assert clean("<p><extref href='x'>WO 245</extref>, and more</p>") == "WO 245, and more"


def test_an_encoded_tag_is_not_turned_into_one():
    assert clean("a &lt;b&gt; c") == "a <b> c"


def test_nothing_is_empty():
    assert clean(None) == "" and clean("") == "" and clean(3) == ""


# --------------------------------------------------------------------------- #
# Ids, references, codes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C8853102", "C8853102"),
        ("c8853102", "C8853102"),
        ("D651997", "D651997"),
        ("A13530124", "A13530124"),
        ("070d55720ea74c86a80597cf79302102", "070d55720ea74c86a80597cf79302102"),
        ("9DA3CCF5-F34D-473A-B2F2-894DE8E810D4", "9da3ccf5-f34d-473a-b2f2-894de8e810d4"),
        ("WO 97/1211/256", None),
        ("C8853102/x", None),
        ("../C1", None),
        ("", None),
    ],
)
def test_ids(raw, expected):
    assert as_id(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("WO 97/1211/256", "WO 97/1211/256"),
        ("wo97/1211/256", "WO 97/1211/256"),
        ("  WO  97 / 1211 / 256 ", "WO 97/1211/256"),
        ("WO 12", "WO 12"),
        ("prob 11/551/352", "PROB 11/551/352"),
        ("Add MS 2741", "Add MS 2741"),
        ("x" * 121, None),
        ("WO 97\n/1", "WO 97/1"),
        ("WO 97\x00", None),
    ],
)
def test_references(raw, expected):
    assert as_reference(raw) == expected


def test_series_and_department_codes():
    assert as_series("wo97") == "WO 97" and as_series("PROB 11") == "PROB 11"
    assert as_series("WO 97/1211") is None and as_series("97") is None
    assert as_department("wo") == "WO" and as_department("WO 97") is None


def test_wo97_items_are_told_from_pieces_and_other_series():
    assert is_wo97_item("WO 97/1211/256")
    assert not is_wo97_item("WO 97/1211")
    assert not is_wo97_item("WO 971/1/2")
    assert not is_wo97_item("WO 12/4812")


def test_levels_are_named_for_tnas_records_only():
    assert level_of(7, True) == {"level": 7, "level_name": "item"}
    assert level_of(9, False) == {"level": 9}
    assert level_of(None, True) == {}


def test_the_record_page():
    assert record_url("C8853102") == "https://discovery.nationalarchives.gov.uk/details/r/C8853102"


# --------------------------------------------------------------------------- #
# WO 97's standard description
# --------------------------------------------------------------------------- #
def test_the_standard_description_is_taken_apart():
    # WO 97/1211/256: covering dates 1811-1835.
    text = "JOHN ATKINSON Born MANCHESTER, Lancashire Served in Royal Artillery Discharged aged 41."
    s = parse_wo97(text, 18110101, 18351231)
    assert s == {
        "name": "JOHN ATKINSON",
        "surname": "ATKINSON",
        "forenames": "JOHN",
        "birthplace": "MANCHESTER",
        "county": "Lancashire",
        "regiments": ["Royal Artillery"],
        "discharge_age": 41,
        "service_years": "1811-1835",
        "discharge_year": 1835,
        "estimated_birth_year": 1794,
        "birth_year_range": [1793, 1794],
        "original": text,
    }


def test_the_markup_of_a_record_parses_the_same_as_a_search_hit():
    raw = fixture("details_C8853102.json")["scopeContent"]["description"]
    s = parse_wo97(raw, 18110101, 18351231)
    assert s["birthplace"] == "MANCHESTER" and s["discharge_age"] == 41
    assert s["original"].startswith("JOHN ATKINSON Born MANCHESTER")


def test_an_alias_is_kept():
    # WO 97/810/60.
    s = parse_wo97(
        "JAMES HARGRAVES alias JAMES HARGREAVES Born SKIPTON, Yorkshire Served in 68th Foot "
        "Regiment Discharged aged 36.",
        18270101,
        18431231,
    )
    assert s["name"] == "JAMES HARGRAVES" and s["aliases"] == ["JAMES HARGREAVES"]
    assert s["surname"] == "HARGRAVES" and s["estimated_birth_year"] == 1807


def test_several_regiments_are_split():
    # WO 97/918/6.
    s = parse_wo97(
        "JONAS HARGREAVES Born OVENDEN, Yorkshire Served in 82nd Foot Regiment; Yorkshire "
        "Militia Discharged aged 45.",
        18030101,
        18251231,
    )
    assert s["regiments"] == ["82nd Foot Regiment", "Yorkshire Militia"]


def test_a_single_covering_year_that_is_the_discharge():
    # WO 97/936/21: covering date 1806.
    s = parse_wo97(
        "RICHARD HARGREAVES Born PLUNGES, Leicestershire Served in 84th Foot Regiment "
        "Discharged aged 32 Covering date gives year of discharge.",
        18060101,
        18061231,
    )
    assert s["discharge_year"] == 1806 and "service_years" not in s
    assert s["estimated_birth_year"] == 1774
    assert s["covering_note"] == "Covering date gives year of discharge."


def test_a_single_covering_year_that_is_the_enlistment():
    # WO 97/1209/85: covering date 1845.
    s = parse_wo97(
        "PETER SULLIVAN Born AT SEA, England Served in Madras Artillery Discharged aged "
        "[Not Known] Covering date gives year of enlistment.",
        18450101,
        18451231,
    )
    assert s["enlistment_year"] == 1845 and s["discharge_year"] is None
    assert s["discharge_age"] is None and s["discharge_age_text"] == "[Not Known]"
    assert "estimated_birth_year" not in s


def test_a_birthplace_with_no_county():
    # WO 97/534/96.
    s = parse_wo97(
        "WILLIAM ROWLES Born AT SEA IN REGIMENT Served in 36th Foot Regiment Discharged aged 21.",
        18210101,
        18271231,
    )
    assert s["birthplace"] == "AT SEA IN REGIMENT" and "county" not in s


def test_unspecified_regiments_are_flagged_not_listed():
    # WO 97/688/73.
    s = parse_wo97(
        "JOHN R BOND Born AT SEA IN F77 Served in Albany Staff; 69th Foot Regiment; 56th Foot "
        "Regiment; other regiment(s) unspecified Discharged aged 43.",
        18120101,
        18381231,
    )
    assert s["regiments"] == ["Albany Staff", "69th Foot Regiment", "56th Foot Regiment"]
    assert s["other_regiments_unspecified"] is True
    assert s["forenames"] == "JOHN R"


def test_a_man_with_one_name():
    # Constructed on the pattern of WO 97/1183/44, a man recorded by one name.
    s = parse_wo97(
        "CAESAR Born Africa Served in Royal African Corps; Corps of Military Labourers "
        "Discharged aged [Not Known].",
        18150101,
        18431231,
    )
    assert s["surname"] == "CAESAR" and s["forenames"] == ""
    assert s["birthplace"] == "Africa" and len(s["regiments"]) == 2


def test_a_piece_or_any_other_text_is_not_parsed():
    piece = fixture("details_C604905_piece.json")["scopeContent"]["description"]
    assert parse_wo97(piece, 17600101, 18541231) is None  # "Royal Artillery: And - Ayt"
    assert parse_wo97("", None, None) is None
    assert parse_wo97("Served in Royal Artillery", None, None) is None


def test_born_is_matched_with_its_capital_only():
    # Constructed to test the marker; not a recorded entry.
    s = parse_wo97(
        "JOHN BORNE Born BORNHOLM, Denmark Served in 1st Foot Regiment Discharged aged 30.",
        18000101,
        18101231,
    )
    assert s["name"] == "JOHN BORNE" and s["birthplace"] == "BORNHOLM"


# --------------------------------------------------------------------------- #
# Loose matching
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "wanted", ["33rd Foot", "33 Foot", "33rd Regiment of Foot", "33rd", "foot", "33rd Ft"]
)
def test_a_regiment_matches_loosely(wanted):
    assert regiment_matches(wanted, ["33rd Foot Regiment"])


@pytest.mark.parametrize("wanted", ["34th Foot", "Royal Artillery", "33rd Dragoons"])
def test_a_different_regiment_does_not(wanted):
    assert not regiment_matches(wanted, ["33rd Foot Regiment"])


def test_regiment_words_must_all_be_in_one_regiment():
    regiments = ["Royal Newfoundland Veterans", "33rd Foot Regiment"]
    assert regiment_matches("33rd Foot", regiments)
    assert not regiment_matches("33rd Veterans", regiments)


def test_plurals_fold():
    assert regiment_matches("Dragoons", ["6th Dragoon Guards"])
    assert regiment_matches("2nd Dragoon Guards", ["2nd Dragoon Guards"])


def test_a_place_matches_on_town_or_county():
    assert place_matches("Manchester", "MANCHESTER", "Lancashire")
    assert place_matches("lancashire", "MANCHESTER", "Lancashire")
    assert place_matches("Kirkby Stephen", "KIRKBY STEPHEN", "Westmorland")
    assert not place_matches("Leeds", "MANCHESTER", "Lancashire")


def test_names_match_whole_or_by_prefix():
    assert name_matches("Atkinson", "ATKINSON")
    assert not name_matches("Atkin", "ATKINSON")
    assert name_matches("Hargr*", "HARGRAVES")
    assert name_matches("o'brian", "OBRIAN")


def test_entities_keep_their_text_and_the_id_they_point_at():
    rows = entity_lines(fixture("details_C14305_series.json")["detailedRelatedMaterial"])
    assert {"text": "First World War soldiers' documents are in WO 363", "id": "C14567"} in rows
    assert all(row["text"] for row in rows)
