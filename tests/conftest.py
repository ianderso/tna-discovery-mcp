"""Shared fixtures. Every test runs against a mocked Discovery; nothing touches the network.

The fixtures under ``fixtures/`` are real answers from Discovery's API,
recorded on 2026-10-11 (see docs/API-NOTES.md) and trimmed: a search page
keeps only some of its records, and the 500 error page keeps only its status
and title. The records are historical: soldiers discharged to a Chelsea
pension between 1793 and 1854 (WO 97), a 1716 will (PROB 11), First World War
war diaries (WO 95), and the WO 97 and WO 12 series themselves.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from tna_discovery_mcp import server
from tna_discovery_mcp.client import API_HOST, DiscoveryHttp
from tna_discovery_mcp.config import Config

FIXTURES = Path(__file__).parent / "fixtures"

#: Where every request goes.
API = f"https://{API_HOST}/API"


def fixture(name: str) -> Any:
    """Load one recorded response: JSON for .json files, text otherwise."""
    path = FIXTURES / name
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return path.read_text(encoding="utf-8")


def status_text(name: str) -> httpx.Response:
    """A recorded error saved as ``<status>\\n<body>``."""
    status, _, body = fixture(name).partition("\n")
    return httpx.Response(int(status), text=body, headers={"content-type": "text/html"})


def make_http(tmp_path: Path, **kwargs) -> DiscoveryHttp:
    """A client with no pacing and no back-off, counting calls under ``tmp_path``."""
    options = {"min_interval": 0.0, "backoff": 0.0}
    options.update(kwargs)
    return DiscoveryHttp(tmp_path / "state", **options)


@pytest.fixture
def http(tmp_path) -> DiscoveryHttp:
    return make_http(tmp_path)


@pytest.fixture
def served(tmp_path, monkeypatch) -> DiscoveryHttp:
    """Install a fast test client as the server's client for the duration of a test."""
    c = make_http(tmp_path)
    monkeypatch.setattr(server.runtime, "http", c)
    monkeypatch.setattr(server.runtime, "config", Config(state_dir=tmp_path / "state"))
    return c


@pytest.fixture
def site():
    """A respx router. Any request it does not expect fails the test."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


Answer = Any  # dict | list | str | httpx.Response | Callable[[httpx.Request], ...]


def route_api(router: respx.MockRouter, answers: dict[str, Answer]) -> respx.Route:
    """Answer Discovery's requests from ``answers``, keyed by path after ``/API``.

    A path is looked up whole first, then by its longest matching prefix. A
    value is JSON (dict or list), text, an ``httpx.Response``, or a callable
    taking the request and returning one of those. Anything unanswered is a
    599, so a test that reaches it fails loudly.
    """

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode().split("?")[0].removeprefix("/API")
        answer = answers.get(path)
        if answer is None:
            prefixes = sorted((k for k in answers if path.startswith(k)), key=len, reverse=True)
            answer = answers[prefixes[0]] if prefixes else None
        if callable(answer):
            answer = answer(request)
        if answer is None:
            return httpx.Response(599, text=f"unmocked {request.url}")
        if isinstance(answer, httpx.Response):
            return answer
        if isinstance(answer, str):
            return httpx.Response(200, text=answer, headers={"content-type": "text/html"})
        return httpx.Response(200, json=answer)

    return router.route(host=API_HOST).mock(side_effect=respond)


#: The recorded answers, by path. %2F is how a reference's slashes travel.
RECORDED: dict[str, Answer] = {
    "/records/v1/details/C8853102": fixture("details_C8853102.json"),
    "/records/v1/context/C8853102": fixture("context_C8853102.json"),
    "/records/v1/details/C8799436": fixture("details_C8799436_single_year.json"),
    "/records/v1/details/C8783579": fixture("details_C8783579_alias.json"),
    "/records/v1/details/C14305": fixture("details_C14305_series.json"),
    "/records/v1/details/C604905": fixture("details_C604905_piece.json"),
    "/records/v1/details/D651997": fixture("details_D651997_digitised.json"),
    "/records/v1/collection/WO%2097%2F1211%2F256": fixture("collection_wo97_1211_256.json"),
    "/records/v1/collection/WO%2012": fixture("collection_wo12.json"),
    "/records/v1/children/C14305": fixture("children_C14305_wo97.json"),
    "/records/v1/children/C14223": fixture("children_C14223_wo12.json"),
}


def discovery(router: respx.MockRouter, **extra: Answer) -> respx.Route:
    """Discovery, answering from the recorded fixtures; ``extra`` adds or overrides paths.

    Keyword names cannot carry slashes, so ``extra`` keys use ``__`` for ``/``.
    """
    answers = dict(RECORDED)
    answers.update({k.replace("__", "/"): v for k, v in extra.items()})
    return route_api(router, answers)


def searched(answer: Answer) -> dict[str, Answer]:
    """The search path answering with ``answer``."""
    return {"/search/v1/records": answer}


async def call_tool(tool_name: str, /, **arguments) -> dict:
    """Invoke a tool the way a client does, so Field defaults are resolved."""
    result = await server.mcp.call_tool(tool_name, arguments)
    return json.loads(result.content[0].text)


def params_of(route: respx.Route, index: int = -1) -> list[tuple[str, str]]:
    """The query parameters of one recorded call, in order."""
    return list(route.calls[index].request.url.params.multi_items())


# --------------------------------------------------------------------------- #
# Argument building for whole-surface sweeps
# --------------------------------------------------------------------------- #
#: Errors a tool returns from its own input checks, before any work. A sweep
#: that gets one of these has not tested what it thinks it has.
LOCAL_VALIDATION_ERRORS = frozenset(
    {
        "no_criteria",
        "no_target",
        "invalid_reference",
        "invalid_query",
        "invalid_series",
        "invalid_department",
        "invalid_date",
        "invalid_held_by",
        "invalid_after",
        "invalid_surname",
        "invalid_forename",
        "invalid_year",
        "invalid_filter",
        "too_deep",
    }
)

#: Arguments that carry each tool past its own checks.
VALID_ARGS: dict[str, dict] = {
    "search_records": {"query": "hargreaves", "series": "WO 97"},
    "get_record": {"id_or_reference": "C8853102"},
    "browse": {"reference_or_id": "C14305"},
    "find_soldier": {"surname": "Atkinson", "discharged_from": 1831, "discharged_to": 1834},
    "budget_status": {},
}


def valid_args(tool_name: str) -> dict:
    """VALID_ARGS for one tool."""
    return dict(VALID_ARGS[tool_name])


def assert_reached_body(tool_name: str, result) -> None:
    """Fail if a sweep stopped at input validation instead of the tool's body."""
    if isinstance(result, dict) and result.get("error") in LOCAL_VALIDATION_ERRORS:
        raise AssertionError(
            f"{tool_name} rejected the sweep's arguments with {result['error']!r}; "
            f"update VALID_ARGS in tests/conftest.py. Message: {result.get('message')!r}"
        )


def every_request(router: respx.MockRouter, respond: Callable[[httpx.Request], Any]):
    """Route every request to Discovery to one handler."""
    return router.route(host=API_HOST).mock(side_effect=respond)
