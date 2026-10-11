"""The tools, called as a client calls them, against recorded answers."""

from __future__ import annotations

import httpx
import pytest

from tna_discovery_mcp import server

from .conftest import (
    call_tool,
    discovery,
    fixture,
    params_of,
    route_api,
    searched,
    status_text,
)


# --------------------------------------------------------------------------- #
# search_records
# --------------------------------------------------------------------------- #
async def test_a_search_sends_tidied_filters(served, site):
    route = discovery(site, **{"__search__v1__records": fixture("search_wo97_hargreaves.json")})
    out = await call_tool(
        "search_records",
        query="hargreaves",
        series="wo97",
        date_from="1831",
        date_to="1834-06",
        held_by="tna",
        department="wo",
        sort="reference",
        count=25,
        page=2,
    )
    assert params_of(route) == [
        ("sps.searchQuery", "hargreaves"),
        ("sps.recordSeries", "WO 97"),
        ("sps.departments", "WO"),
        ("sps.dateFrom", "1831-01-01"),
        ("sps.dateTo", "1834-06-30"),
        ("sps.heldByCode", "TNA"),
        ("sps.sortByOption", "REFERENCE_ASCENDING"),
        ("sps.resultsPageSize", "25"),
        ("sps.page", "2"),
    ]
    assert out["filters"] == {
        "series": "WO 97",
        "department": "WO",
        "date_from": "1831-01-01",
        "date_to": "1834-06-30",
        "held_by": "TNA",
    }


async def test_a_search_hit_carries_what_a_citation_needs(served, site):
    discovery(site, **{"__search__v1__records": fixture("search_wo97_hargreaves.json")})
    out = await call_tool("search_records", query="hargreaves", series="WO 97")
    assert out["total"] == 30 and out["returned"] == 22 and out["next_page"] == 2
    first = out["records"][0]
    assert first["id"] == "C8862658" and first["reference"] == "WO 97/1234/9"
    assert first["description"].startswith("GEORGE HARGREAVES Born HASLINGDEN")
    assert "title" not in first  # the title only repeats the description
    assert first["covering_dates"] == "1793-1795"
    assert first["held_by"] == "The National Archives, Kew"
    assert first["level"] == 7 and first["level_name"] == "item"
    assert first["digitised"] is False
    assert first["context"].startswith("Royal Hospital Chelsea: Soldiers Service Documents")
    assert first["url"] == "https://discovery.nationalarchives.gov.uk/details/r/C8862658"
    assert first["soldier"]["birthplace"] == "HASLINGDEN"
    assert "original" not in first["soldier"]
    assert out["by_held_by"] == [{"code": "TNA", "count": 30}]


async def test_a_title_cut_short_is_not_repeated(served, site):
    discovery(site, **{"__search__v1__records": fixture("search_wo97_hargreaves.json")})
    out = await call_tool("search_records", query="hargreaves", series="WO 97")
    alias = next(r for r in out["records"] if r["reference"] == "WO 97/810/60")
    assert "title" not in alias and alias["description"].endswith("aged 36.")


async def test_digitised_records_are_flagged(served, site):
    discovery(site, **{"__search__v1__records": fixture("search_wo95_digitised.json")})
    out = await call_tool("search_records", query="battalion", series="WO 95")
    assert all(r["digitised"] for r in out["records"])
    assert out["records"][0]["id"] == "070d55720ea74c86a80597cf79302102"
    assert out["by_century"] == [{"code": "1900", "count": 3180}]


async def test_a_piece_search_finds_a_regiment_in_a_year(served, site):
    route = discovery(site, **searched(fixture("search_wo12_33rd_foot_1821.json")))
    out = await call_tool(
        "search_records", query='"33rd foot"', series="WO 12", date_from="1821", date_to="1821"
    )
    assert params_of(route)[0] == ("sps.searchQuery", '"33rd foot"')
    [piece] = out["records"]
    assert piece["reference"] == "WO 12/4812" and piece["level_name"] == "piece"
    assert "soldier" not in piece


async def test_held_by_takes_an_archon_code_or_other(served, site):
    route = discovery(site, **searched(fixture("search_wo95_digitised.json")))
    await call_tool("search_records", query="muster roll", held_by="182")
    assert ("sps.recordRepositories", "182") in params_of(route)
    await call_tool("search_records", query="muster roll", held_by="other")
    assert ("sps.heldByCode", "OTH") in params_of(route)


async def test_a_series_alone_lists_it(served, site):
    route = discovery(site, **searched(fixture("search_wo97_hargreaves.json")))
    await call_tool("search_records", series="WO 97")
    assert params_of(route)[0] == ("sps.searchQuery", "*")


def test_a_repository_facet_names_its_archon_code():
    rows = [{"code": "182 Example Record Office", "count": 55}, {"code": "TNA", "count": 3}]
    assert server._facet(rows, repository=True) == [
        {"archon": "182", "name": "Example Record Office", "count": 55},
        {"code": "TNA", "count": 3},
    ]


async def test_a_zero_says_what_it_covers(served, site):
    empty = {**fixture("search_wo97_hargreaves.json"), "records": [], "count": 0}
    discovery(site, **searched(empty))
    out = await call_tool("search_records", query="zzzz", series="WO 97")
    assert out["total"] == 0 and out["next_page"] is None
    assert "spellings vary" in out["note"]


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ({}, "no_criteria"),
        ({"query": "x", "series": "WO 97/1211"}, "invalid_series"),
        ({"query": "x", "department": "WO 97"}, "invalid_department"),
        ({"query": "x", "date_from": "1831-13"}, "invalid_date"),
        ({"query": "x", "date_to": "June 1831"}, "invalid_date"),
        ({"query": "x", "date_from": "1831-02-30"}, "invalid_date"),
        ({"query": "x", "held_by": "kew archives"}, "invalid_held_by"),
        ({"query": "x\x00y"}, "invalid_query"),
        ({"query": "x", "count": 100, "page": 101}, "too_deep"),
    ],
)
async def test_bad_search_arguments_are_refused_before_any_request(served, site, args, error):
    route = discovery(site)
    out = await call_tool("search_records", **args)
    assert out["error"] == error and route.call_count == 0


async def test_a_bare_year_never_reaches_discovery_as_one(served, site):
    """Discovery answers a bare year with a 500; the server sends a full date."""
    route = route_api(
        site,
        searched(
            lambda request: (
                status_text("error_500_bare_year.txt")
                if len(request.url.params.get("sps.dateFrom", "")) == 4
                else httpx.Response(200, json=fixture("search_wo97_hargreaves.json"))
            )
        ),
    )
    out = await call_tool("search_records", query="hargreaves", date_from="1831")
    assert "error" not in out and route.call_count == 1


async def test_an_outage_is_not_an_empty_result(served, site):
    route_api(site, searched(status_text("error_500_bare_year.txt")))
    out = await call_tool("search_records", query="hargreaves")
    assert out["error"] == "upstream_error" and "not an empty result" in out["message"]


# --------------------------------------------------------------------------- #
# get_record
# --------------------------------------------------------------------------- #
async def test_a_wo97_item_is_read_parsed_placed_and_citable(served, site):
    route = discovery(site)
    out = await call_tool("get_record", id_or_reference="C8853102")
    assert route.call_count == 2  # details and context
    assert out["reference"] == "WO 97/1211/256"
    assert out["description"].startswith("JOHN ATKINSON\nBorn MANCHESTER")
    assert out["covering_dates"] == "1811-1835" and out["level_name"] == "item"
    assert out["held_by"] == ["The National Archives, Kew"] and out["digitised"] is False
    assert out["parent_id"] == "C604905" and out["has_children"] is False
    soldier = out["soldier"]
    assert soldier["name"] == "JOHN ATKINSON" and soldier["county"] == "Lancashire"
    assert soldier["regiments"] == ["Royal Artillery"] and soldier["discharge_age"] == 41
    assert soldier["service_years"] == "1811-1835" and soldier["estimated_birth_year"] == 1794
    assert soldier["original"].startswith("JOHN ATKINSON Born MANCHESTER")
    assert [h.get("reference") for h in out["hierarchy"]] == [
        "WO",
        None,
        "WO 97",
        None,
        "WO 97/1211",
    ]
    assert out["hierarchy"][-1]["title"] == "Royal Artillery: And - Ayt"
    assert out["series"] == {
        "reference": "WO 97",
        "title": "Royal Hospital Chelsea: Soldiers Service Documents",
    }
    assert "Findmypast" in out["images"] and "1952868" in out["images"]
    assert out["citation"] == {
        "institution": "The National Archives, Kew",
        "reference": "WO 97/1211/256",
        "title": "Royal Hospital Chelsea: Soldiers Service Documents",
        "covering_dates": "1811-1835",
        "url": "https://discovery.nationalarchives.gov.uk/details/r/C8853102",
        "cite_as": "The National Archives, Kew, WO 97/1211/256",
    }


async def test_a_reference_is_looked_up_first(served, site):
    route = discovery(site)
    out = await call_tool("get_record", id_or_reference="wo 97/1211/256", hierarchy=False)
    paths = [c.request.url.raw_path.decode() for c in route.calls]
    assert paths == [
        "/API/records/v1/collection/WO%2097%2F1211%2F256?limit=10",
        "/API/records/v1/details/C8853102",
    ]
    assert out["id"] == "C8853102" and "hierarchy" not in out


async def test_a_reference_nobody_uses_is_not_found(served, site):
    discovery(site, **{"__records__v1__collection__": fixture("collection_empty.json")})
    out = await call_tool("get_record", id_or_reference="WO 97/99999")
    assert out["error"] == "not_found" and "exact" in out["message"]


async def test_a_reference_two_archives_use_asks_which(served, site):
    one = fixture("collection_wo12.json")["assets"][0]
    other = {**one, "id": "N13554877", "heldBy": [{"xReferenceName": "Example Record Office"}]}
    discovery(
        site,
        **{"__records__v1__collection__WO%2012": {"assets": [one, other]}},
    )
    out = await call_tool("get_record", id_or_reference="WO 12")
    assert out["error"] == "several_records"
    assert [m["id"] for m in out["matches"]] == ["C14223", "N13554877"]


async def test_an_unknown_id_is_not_found(served, site):
    discovery(site, **{"__records__v1__details__C99": httpx.Response(204)})
    out = await call_tool("get_record", id_or_reference="C99")
    assert out["error"] == "not_found"


async def test_a_single_year_discharge_is_dated_by_it(served, site):
    discovery(site)
    out = await call_tool("get_record", id_or_reference="C8799436", hierarchy=False)
    assert out["soldier"]["discharge_year"] == 1806
    assert out["soldier"]["covering_note"] == "Covering date gives year of discharge."


async def test_a_series_record_carries_its_long_fields_and_related_series(served, site):
    discovery(site)
    out = await call_tool("get_record", id_or_reference="C14305", hierarchy=False)
    assert out["reference"] == "WO 97" and out["level_name"] == "series"
    assert out["title"] == "Royal Hospital Chelsea: Soldiers Service Documents"
    assert out["description"].startswith("This is the main series of service documents")
    assert out["arrangement"].startswith("The documents are arranged in three series")
    assert out["extent"] == "6383 boxes and files"
    assert out["creators"] == [{"text": "Royal Hospital Chelsea"}]
    assert any(r.get("id") == "C14567" for r in out["related_material"])
    assert "soldier" not in out and "Findmypast" in out["images"]


async def test_a_digitised_record_says_where_its_image_is(served, site):
    discovery(site)
    out = await call_tool("get_record", id_or_reference="D651997", hierarchy=False)
    assert out["digitised"] is True and "digitised" in out["images"]
    assert out["description"] == "W Josia Hargreaves"
    assert out["citation"]["cite_as"] == "The National Archives, Kew, PROB 11/551/352"


async def test_a_piece_has_no_soldier(served, site):
    discovery(site)
    out = await call_tool("get_record", id_or_reference="C604905", hierarchy=False)
    assert out["level_name"] == "piece" and out["has_children"] is True
    assert out["description"] == "Royal Artillery: And - Ayt" and "soldier" not in out


@pytest.mark.parametrize("value", ["", "   ", "WO 97\x00/1"])
async def test_an_unusable_target_is_refused_before_any_request(served, site, value):
    route = discovery(site)
    out = await call_tool("get_record", id_or_reference=value)
    assert out["error"] in ("no_target", "invalid_reference") and route.call_count == 0


# --------------------------------------------------------------------------- #
# browse
# --------------------------------------------------------------------------- #
async def test_browse_lists_a_series_children(served, site):
    route = discovery(site)
    out = await call_tool("browse", reference_or_id="C14305", limit=10)
    assert params_of(route) == [("limit", "10")]
    assert out["parent_id"] == "C14305" and out["returned"] == 7
    first = out["children"][0]
    assert first["id"] == "C28938" and first["level_name"] == "sub-series"
    assert first["description"].startswith("1760-1854: discharge papers")
    assert first["has_children"] is True and out["next_after"] is None


async def test_browse_by_reference_names_the_parent(served, site):
    route = discovery(site)
    out = await call_tool("browse", reference_or_id="WO 12", limit=20)
    assert route.call_count == 2
    assert out["parent_reference"] == "WO 12"
    assert out["parent_description"].startswith("Commissary General of Musters")
    assert out["children"][0]["description"] == "CAVALRY"
    piece = next(c for c in out["children"] if c.get("reference") == "WO 12/603")
    assert piece["description"] == "3rd Hussars" and piece["level_name"] == "piece"
    assert out["next_after"] == "06 0 5606000 0#606000"  # the last child's sort key


async def test_browse_continues_after_a_cursor_without_repeating_it(served, site):
    route = discovery(
        site,
        **{
            "__records__v1__children__C28938": lambda request: fixture(
                "children_C28938_after.json"
                if request.url.params.get("batchStartMark")
                else "children_C28938_first.json"
            )
        },
    )
    first = await call_tool("browse", reference_or_id="C28938", limit=5)
    assert [c["reference"] for c in first["children"]] == [f"WO 97/{n}" for n in range(1, 6)]
    cursor = first["next_after"]
    assert cursor == "06 0 35000 0#5000"
    second = await call_tool("browse", reference_or_id="C28938", limit=2, after=cursor)
    assert params_of(route) == [
        ("limit", "3"),
        ("batchStartMark", cursor),
        ("direction", "NEXT"),
    ]
    assert [c["reference"] for c in second["children"]] == ["WO 97/6", "WO 97/7"]
    assert second["next_after"] == "06 0 37000 0#7000"


async def test_browse_of_a_leaf_says_so(served, site):
    discovery(
        site,
        **{"__records__v1__children__C601723": {"assets": [], "hasMoreAfterLast": False}},
    )
    out = await call_tool("browse", reference_or_id="C601723")
    assert out["children"] == [] and "piece or an item" in out["note"]


# --------------------------------------------------------------------------- #
# find_soldier
# --------------------------------------------------------------------------- #
FIND = {"__search__v1__records": fixture("find_atkinson_1831_1834.json")}


async def test_find_soldier_searches_wo97_for_the_name_and_overlap(served, site):
    route = discovery(site, **FIND)
    await call_tool("find_soldier", surname="Atkinson", discharged_from=1831, discharged_to=1834)
    assert params_of(route) == [
        ("sps.searchQuery", "Atkinson"),
        ("sps.recordSeries", "WO 97"),
        ("sps.dateFrom", "1831-01-01"),
        ("sps.dateTo", "1834-12-31"),
        ("sps.sortByOption", "REFERENCE_ASCENDING"),
        ("sps.resultsPageSize", "500"),
        ("sps.page", "1"),
    ]


async def test_find_soldier_keeps_only_men_discharged_in_the_range(served, site):
    discovery(site, **FIND)
    out = await call_tool(
        "find_soldier", surname="Atkinson", discharged_from=1831, discharged_to=1834
    )
    assert out["total"] == 37 and out["scanned"] == 27
    assert [s["reference"] for s in out["soldiers"]] == ["WO 97/1211/251", "WO 97/1211/257"]
    assert out["excluded"]["discharge_year"] == 25
    man = out["soldiers"][0]
    assert man["name"] == "JAMES ATKINSON" and man["discharge_year"] == 1832
    assert man["estimated_birth_year"] == 1794 and man["birth_year_range"] == [1793, 1794]
    assert man["url"].endswith("/C8853097") and man["covering_dates"] == "1811-1832"
    assert "Findmypast" in out["images"] and "never by name" in out["note"]


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"regiment": "Royal Horse Artillery"}, ["WO 97/1211/257"]),
        ({"regiment": "Royal Artillery"}, ["WO 97/1211/251", "WO 97/1211/257"]),
        ({"birthplace": "Manchester"}, ["WO 97/1211/251"]),
        ({"birthplace": "Tipperary"}, ["WO 97/1211/257"]),
        ({"forename": "James"}, ["WO 97/1211/251"]),
        ({"forename": "Jo*"}, ["WO 97/1211/257"]),
        ({"regiment": "33rd Foot"}, []),
    ],
)
async def test_find_soldier_filters(served, site, filters, expected):
    discovery(site, **FIND)
    out = await call_tool(
        "find_soldier", surname="Atkinson", discharged_from=1831, discharged_to=1834, **filters
    )
    assert [s["reference"] for s in out["soldiers"]] == expected


async def test_find_soldier_puts_the_forename_in_the_query(served, site):
    route = discovery(site, **FIND)
    await call_tool("find_soldier", surname="Atkinson", forename="James")
    assert params_of(route)[0] == ("sps.searchQuery", "James Atkinson")
    assert ("sps.dateFrom", "1831-01-01") not in params_of(route)


async def test_find_soldier_matches_aliases_and_drops_other_surnames(served, site):
    discovery(site, **{"__search__v1__records": fixture("search_wo97_hargreaves.json")})
    out = await call_tool("find_soldier", surname="Hargreaves")
    references = [s["reference"] for s in out["soldiers"]]
    assert "WO 97/810/60" in references  # JAMES HARGRAVES alias JAMES HARGREAVES
    assert "WO 97/668/23" not in references  # HARGREAVES TILLOTSON
    assert "WO 97/918/5" not in references  # EDWARD HARGREAVE alias EDWARD HARGRAVES
    assert out["excluded"]["other_surname"] == 4
    wild = await call_tool("find_soldier", surname="Hargr*")
    assert "WO 97/918/5" in [s["reference"] for s in wild["soldiers"]]


async def test_a_man_whose_date_is_his_enlistment_is_kept_unless_he_enlisted_too_late():
    enlisted_1845 = {"discharge_year": None, "enlistment_year": 1845}
    assert server._discharge_fits(enlisted_1845, 1850, 1854)
    assert not server._discharge_fits(enlisted_1845, 1831, 1834)
    assert server._discharge_fits({"discharge_year": 1832}, 1831, None)


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ({"surname": ""}, "invalid_surname"),
        ({"surname": "Atkinson Hargreaves"}, "invalid_surname"),
        ({"surname": "Atkinson OR x"}, "invalid_surname"),
        ({"surname": "At(kinson"}, "invalid_surname"),
        ({"surname": "Atkinson", "forename": "J0hn"}, "invalid_forename"),
        ({"surname": "Atkinson", "discharged_from": 1600}, "invalid_year"),
        ({"surname": "Atkinson", "discharged_from": 1840, "discharged_to": 1830}, "invalid_year"),
        ({"surname": "Atkinson", "regiment": "a\nb"}, "invalid_filter"),
        ({"surname": "Atkinson", "page": 21}, "too_deep"),
    ],
)
async def test_bad_find_soldier_arguments_are_refused_before_any_request(served, site, args, error):
    route = discovery(site)
    out = await call_tool("find_soldier", **args)
    assert out["error"] == error and route.call_count == 0


# --------------------------------------------------------------------------- #
# budget_status and the budget as the tools see it
# --------------------------------------------------------------------------- #
async def test_budget_status_counts_todays_requests(served, site):
    discovery(site)
    await call_tool("get_record", id_or_reference="C8853102")
    out = await call_tool("budget_status")
    assert out["calls_today"] == 2 and out["calls_this_session"] == 2
    assert out["daily_budget"] == 3_000 and out["remaining_today"] == 2_998
    assert out["last_error"] is None and "cached" in out["note"]


async def test_a_spent_budget_is_a_structured_refusal(tmp_path, monkeypatch, site):
    from .conftest import make_http

    http = make_http(tmp_path, daily_budget=1)
    monkeypatch.setattr(server.runtime, "http", http)
    route = discovery(site)
    out = await call_tool("get_record", id_or_reference="C8853102")
    assert out["error"] == "budget_spent" and route.call_count == 1
    assert "says nothing about whether the record exists" in out["message"]
    status = await call_tool("budget_status")
    assert status["remaining_today"] == 0 and status["last_error"]["error"] == "budget_spent"


async def test_a_bad_setting_surfaces_on_the_first_call(monkeypatch):
    monkeypatch.setattr(server.runtime, "http", None)
    monkeypatch.setattr(server.runtime, "config", None)
    monkeypatch.setenv("TNA_DISCOVERY_DAILY_BUDGET", "9000")
    out = await call_tool("budget_status")
    assert out["error"] == "not_configured" and "TNA_DISCOVERY_DAILY_BUDGET" in out["message"]
