"""The HTTP client: what it sends, refuses, retries, paces, counts and never keeps."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from tna_discovery_mcp import __version__
from tna_discovery_mcp.client import (
    BUDGET_FILE,
    PROJECT_URL,
    DiscoveryError,
    HostNotAllowed,
    user_agent,
)

from .conftest import API_HOST, discovery, fixture, make_http, route_api, status_text

DETAILS = "/records/v1/details/C8853102"


async def test_the_user_agent_names_the_package_version_and_repository(http, site):
    route = discovery(site)
    await http.get_json(DETAILS)
    agent = route.calls.last.request.headers["user-agent"]
    assert agent == f"tna-discovery-mcp/{__version__} (+{PROJECT_URL})"


def test_a_contact_is_appended_to_the_user_agent():
    assert user_agent("me@example.org").endswith(f"(+{PROJECT_URL}; me@example.org)")


async def test_json_is_asked_for(http, site):
    route = discovery(site)
    await http.get_json(DETAILS)
    assert route.calls.last.request.headers["accept"] == "application/json"


async def test_requests_go_to_the_api_over_https(http, site):
    route = discovery(site)
    await http.get_json(DETAILS)
    url = route.calls.last.request.url
    assert (url.scheme, url.host, url.path) == ("https", API_HOST, "/API" + DETAILS)


async def test_a_request_to_any_other_host_is_refused(http):
    with pytest.raises(HostNotAllowed):
        await http._http.get("https://www.nationalarchives.gov.uk/")


async def test_a_plain_http_request_is_refused_even_to_the_api_host(http):
    with pytest.raises(HostNotAllowed):
        await http._http.get(f"http://{API_HOST}/API/records/v1/details/C1")


async def test_a_redirect_on_the_host_is_followed(http, site):
    target = f"https://{API_HOST}/API/records/v1/details/C8853102"
    answers = iter([httpx.Response(301, headers={"location": target})])

    def respond(request):
        return next(answers, fixture("details_C8853102.json"))

    route_api(site, {"/records/": respond})
    data = await http.get_json("/records/details/C8853102")
    assert data["id"] == "C8853102"


async def test_a_redirect_off_the_host_is_reported_not_followed(http, site):
    target = "https://www.nationalarchives.gov.uk/catalogue/"
    route_api(site, {DETAILS: httpx.Response(302, headers={"location": target})})
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json(DETAILS)
    assert caught.value.code == "redirected" and caught.value.location == target


async def test_an_unknown_id_is_a_204_and_reads_as_not_found(http, site):
    route_api(site, {"/records/v1/details/C99": httpx.Response(204)})
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json("/records/v1/details/C99")
    assert caught.value.code == "not_found" and caught.value.status == 204


async def test_a_web_page_where_json_was_expected_is_not_json(http, site):
    route_api(site, {DETAILS: "<!DOCTYPE html><html></html>"})
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json(DETAILS)
    assert caught.value.code == "not_json" and "web page" in caught.value.detail


async def test_a_bot_challenge_is_named_as_one(http, site):
    route_api(
        site,
        {
            DETAILS: httpx.Response(
                403, text="<title>Just a moment...</title>", headers={"cf-mitigated": "challenge"}
            )
        },
    )
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json(DETAILS)
    assert caught.value.code == "challenge"


async def test_a_429_is_retried_once(http, site):
    answers = iter([httpx.Response(429), fixture("details_C8853102.json")])
    route = route_api(site, {DETAILS: lambda request: next(answers)})
    await http.get_json(DETAILS)
    assert route.call_count == 2


async def test_a_5xx_that_persists_gives_up_after_the_retry(http, site):
    route = route_api(site, {"/search/v1/records": status_text("error_500_bare_year.txt")})
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json("/search/v1/records", [("sps.dateFrom", "1831")])
    assert caught.value.status == 500 and route.call_count == 2
    assert http.last_error["status"] == 500
    assert "Internal Server Error" in caught.value.detail


async def test_a_4xx_is_not_retried(http, site):
    route = route_api(site, {DETAILS: httpx.Response(400, json={"Message": "bad"})})
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json(DETAILS)
    assert caught.value.status == 400 and route.call_count == 1


async def test_a_timeout_is_not_retried(tmp_path, site):
    http = make_http(tmp_path, retries=3)
    route = site.route(host=API_HOST).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json(DETAILS)
    assert caught.value.code == "timeout" and route.call_count == 1


async def test_a_dropped_connection_is_retried(tmp_path, site):
    http = make_http(tmp_path, retries=1)
    route = site.route(host=API_HOST).mock(side_effect=httpx.ConnectError("reset"))
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json(DETAILS)
    assert caught.value.code == "no_response" and route.call_count == 2


async def test_an_answer_over_the_cap_is_refused(tmp_path, site):
    http = make_http(tmp_path, max_json_bytes=100)
    discovery(site)
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json(DETAILS)
    assert caught.value.code == "too_large"


async def test_requests_are_spaced_by_the_minimum_interval(tmp_path, site):
    now = [100.0]
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    http = make_http(tmp_path, min_interval=1.0, clock=lambda: now[0], sleep=fake_sleep)
    discovery(site)
    await http.get_json(DETAILS)
    now[0] += 0.25
    await http.get_json("/records/v1/context/C8853102")
    assert waits == [pytest.approx(0.75)]


async def test_a_repeat_is_asked_again_because_nothing_is_cached(http, site, tmp_path):
    route = discovery(site)
    first = await http.get_json(DETAILS)
    second = await http.get_json(DETAILS)
    assert first == second and route.call_count == 2
    # The only file written is the day's count: a date and a number.
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert [p.name for p in written] == [BUDGET_FILE]
    assert set(json.loads(written[0].read_text())) == {"day", "calls", "updated"}


async def test_identical_concurrent_calls_share_one_request(http, site):
    gate = asyncio.Event()

    async def slow(request):
        await gate.wait()
        return httpx.Response(200, json=fixture("details_C8853102.json"))

    route = site.route(host=API_HOST).mock(side_effect=slow)
    first = asyncio.create_task(http.get_json(DETAILS))
    second = asyncio.create_task(http.get_json(DETAILS))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    gate.set()
    assert await first == await second
    assert route.call_count == 1 and http.shared_waits == 1


# --------------------------------------------------------------------------- #
# The daily budget
# --------------------------------------------------------------------------- #
async def test_every_request_is_counted_retries_and_failures_included(http, site):
    answers = iter([httpx.Response(503), httpx.Response(503)])
    route_api(site, {DETAILS: lambda request: next(answers)})
    with pytest.raises(DiscoveryError):
        await http.get_json(DETAILS)
    day, count = http.day_ledger()
    assert count == 2 and http.live_calls == 2


async def test_a_spent_budget_refuses_without_sending(tmp_path, site):
    http = make_http(tmp_path, daily_budget=2)
    route = discovery(site)
    await http.get_json(DETAILS)
    await http.get_json(DETAILS)
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json(DETAILS)
    assert caught.value.code == "budget_spent"
    assert route.call_count == 2
    assert http.last_error["error"] == "budget_spent"


async def test_the_budget_is_not_retried_past(tmp_path, site):
    """A retry is a request like any other: a spent budget stops it too."""
    http = make_http(tmp_path, daily_budget=1)
    route = route_api(site, {DETAILS: httpx.Response(503)})
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json(DETAILS)
    assert caught.value.code == "budget_spent" and route.call_count == 1


async def test_the_count_is_shared_by_sessions_using_one_state_directory(tmp_path, site):
    discovery(site)
    first = make_http(tmp_path, daily_budget=3)
    await first.get_json(DETAILS)
    await first.get_json(DETAILS)
    second = make_http(tmp_path, daily_budget=3)
    assert second.day_ledger()[1] == 2
    await second.get_json(DETAILS)
    with pytest.raises(DiscoveryError) as caught:
        await second.get_json(DETAILS)
    assert caught.value.code == "budget_spent"


async def test_a_new_day_starts_a_new_count(tmp_path, site):
    today = ["2026-10-11"]
    http = make_http(tmp_path, daily_budget=1, today=lambda: today[0])
    discovery(site)
    await http.get_json(DETAILS)
    with pytest.raises(DiscoveryError):
        await http.get_json(DETAILS)
    today[0] = "2026-10-12"
    await http.get_json(DETAILS)
    assert http.day_ledger() == ("2026-10-12", 1)


async def test_an_unwritable_ledger_still_holds_the_session_to_the_budget(tmp_path, site):
    blocker = tmp_path / "state"
    blocker.write_text("a file where the directory should be")
    http = make_http(tmp_path, daily_budget=1)
    route = discovery(site)
    await http.get_json(DETAILS)
    with pytest.raises(DiscoveryError) as caught:
        await http.get_json(DETAILS)
    assert caught.value.code == "budget_spent" and route.call_count == 1


async def test_a_corrupt_ledger_reads_as_zero(tmp_path, site):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / BUDGET_FILE).write_text("{truncated")
    http = make_http(tmp_path)
    assert http.day_ledger()[1] == 0
    discovery(site)
    await http.get_json(DETAILS)
    assert http.day_ledger()[1] == 1
