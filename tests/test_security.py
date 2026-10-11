"""Every refusal the server makes against arguments a model was steered into.

Tool arguments come from a model, and the model reads text this server does
not control. These tests take the attacker's side: an argument that tries to
leave the API's paths, a public name that leads to a private address, a
redirect off the host, an answer too large to read. Each refusal is checked to
happen before the harm (no lookup, no connection), and each allowed path is
checked to still work.

The tests that need the real transport run it against a stand-in network: DNS
answers come from a table, and each connection replays canned HTTP. Nothing
here leaves the machine.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from types import SimpleNamespace

import httpcore
import pytest

from tna_discovery_mcp import server
from tna_discovery_mcp.client import (
    API_HOST,
    DiscoveryHttp,
    PublicOnlyTransport,
    address_problem,
)
from tna_discovery_mcp.config import Config

from .conftest import call_tool, discovery, fixture, params_of, route_api

#: A public address for the stand-in DNS to give.
PUBLIC = "151.101.1.10"


# --------------------------------------------------------------------------- #
# A stand-in network for the real transport
# --------------------------------------------------------------------------- #
class Resolver:
    """Stands in for ``socket.getaddrinfo``: answers from a table, records every name."""

    def __init__(self) -> None:
        self.answers: dict[str, list[str] | Iterator[list[str]]] = {}
        self.asked: list[str] = []

    def __call__(self, host, port, family=0, type=0, proto=0, flags=0):
        self.asked.append(host)
        answer = self.answers.get(host)
        if answer is not None and not isinstance(answer, list):
            answer = next(answer)
        if answer is None:
            raise socket.gaierror(socket.EAI_NONAME, "not in the test's table")
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (a, port, 0, 0))
            if ":" in a
            else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))
            for a in answer
        ]


class Network(httpcore.AsyncNetworkBackend):
    """Stands in for the internet: records each connection and replays canned HTTP."""

    def __init__(self) -> None:
        self.connects: list[str] = []
        self.replies: list[bytes] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connects.append(host)
        if not self.replies:
            raise httpcore.ConnectError("no route: the suite never touches the network")
        return httpcore.AsyncMockStream([self.replies.pop(0)])

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("no sockets here")

    async def sleep(self, seconds):
        return None


def reply(status: int, body: bytes = b"", *, length: bool = True, **headers: str) -> bytes:
    """One HTTP/1.1 response that closes its connection."""
    lines = [f"HTTP/1.1 {status} Canned", "Connection: close"]
    lines += [f"{k.replace('_', '-')}: {v}" for k, v in headers.items()]
    if length:
        lines.append(f"Content-Length: {len(body)}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


@pytest.fixture
def network(tmp_path, monkeypatch) -> SimpleNamespace:
    """The server's client on the stand-in network, through the real public-only transport."""
    dns, net = Resolver(), Network()
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    http = DiscoveryHttp(
        tmp_path / "state",
        min_interval=0.0,
        backoff=0.0,
        transport=PublicOnlyTransport(backend=net),
    )
    monkeypatch.setattr(server.runtime, "http", http)
    monkeypatch.setattr(server.runtime, "config", Config(state_dir=tmp_path / "state"))
    return SimpleNamespace(http=http, dns=dns, net=net)


# --------------------------------------------------------------------------- #
# Arguments stay inside the API's paths
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value",
    [
        "WO 97/../../search/v1/records",
        "../../../etc/passwd",
        "C8853102?sps.searchQuery=x",
        "WO 97/1211/256#fragment",
        "https://attacker.example/x",
    ],
)
async def test_a_reference_is_one_encoded_path_segment(served, site, value):
    """Whatever a reference holds, it is sent as one percent-encoded segment."""
    route = route_api(site, {"/records/v1/collection/": fixture("collection_empty.json")})
    out = await call_tool("get_record", id_or_reference=value)
    assert out["error"] in ("not_found", "invalid_reference")
    for call in route.calls:
        raw = call.request.url.raw_path.decode()
        assert raw.startswith("/API/records/v1/collection/")
        segment = raw.removeprefix("/API/records/v1/collection/").split("?")[0]
        assert "/" not in segment and "#" not in segment and "?" not in segment
        assert call.request.url.host == API_HOST


async def test_an_id_with_anything_extra_is_a_reference_not_an_id(served, site):
    route = route_api(site, {"/records/v1/collection/": fixture("collection_empty.json")})
    await call_tool("get_record", id_or_reference="C8853102/../C1")
    assert all("/details/" not in c.request.url.path for c in route.calls)


async def test_search_words_travel_as_a_parameter_never_as_a_path(served, site):
    route = discovery(site, **{"__search__v1__records": fixture("search_wo97_hargreaves.json")})
    await call_tool("search_records", query="x&sps.page=99/../../records")
    assert route.calls.last.request.url.path == "/API/search/v1/records"
    assert params_of(route)[0] == ("sps.searchQuery", "x&sps.page=99/../../records")
    assert ("sps.page", "99") not in params_of(route)


async def test_a_cursor_cannot_carry_a_line_break(served, site):
    route = discovery(site)
    out = await call_tool("browse", reference_or_id="C14305", after="x\r\nHost: evil")
    assert out["error"] == "invalid_after" and route.call_count == 0


# --------------------------------------------------------------------------- #
# Which addresses a connection reaches
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.7",
        "172.16.4.2",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "224.0.0.251",
        "240.0.0.1",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:192.168.1.1",
        "64:ff9b::a00:1",
        "2002:a00:1::1",
    ],
)
def test_a_non_public_address_is_named(address):
    assert address_problem(address)


@pytest.mark.parametrize("address", [PUBLIC, "8.8.8.8", "2606:4700:4700::1111"])
def test_a_public_address_passes(address):
    assert address_problem(address) is None


@pytest.mark.parametrize("address", ["10.0.0.7", "127.0.0.1", "169.254.169.254", "fd00::1"])
async def test_the_api_host_leading_to_a_private_address_is_refused_at_connect(network, address):
    network.dns.answers[API_HOST] = [address]
    out = await call_tool("get_record", id_or_reference="C8853102")
    assert out["error"] == "private_address"
    assert address not in out["message"]  # the model is not told the inside address
    assert network.dns.asked == [API_HOST]
    assert network.net.connects == []


async def test_one_private_address_among_public_ones_is_enough_to_refuse(network):
    network.dns.answers[API_HOST] = [PUBLIC, "10.0.0.7"]
    out = await call_tool("get_record", id_or_reference="C8853102")
    assert out["error"] == "private_address" and network.net.connects == []


async def test_a_name_that_changes_its_answer_gains_nothing(network):
    """DNS rebinding: public for the first connection, private for the retry."""
    network.dns.answers[API_HOST] = iter([[PUBLIC], ["127.0.0.1"]])
    out = await call_tool("get_record", id_or_reference="C8853102")
    assert out["error"] == "private_address"
    assert network.dns.asked == [API_HOST] * 2  # checked again, not reused
    assert network.net.connects == [PUBLIC]


async def test_the_connection_goes_to_the_address_that_was_checked(network):
    network.dns.answers[API_HOST] = [PUBLIC]
    body = json.dumps(fixture("details_C8853102.json")).encode()
    network.net.replies += [
        reply(200, body, content_type="application/json"),
        reply(200, b"[]", content_type="application/json"),
    ]
    out = await call_tool("get_record", id_or_reference="C8853102")
    assert out["reference"] == "WO 97/1211/256"
    assert network.net.connects == [PUBLIC, PUBLIC]


async def test_a_redirect_off_the_host_is_not_followed(network):
    network.dns.answers[API_HOST] = [PUBLIC]
    network.net.replies.append(reply(302, location="https://attacker.example/x"))
    out = await call_tool("get_record", id_or_reference="C8853102")
    assert out["error"] == "moved" and network.dns.asked == [API_HOST]
    assert network.net.connects == [PUBLIC]


async def test_an_answer_too_large_is_refused_as_it_streams(network, monkeypatch):
    monkeypatch.setattr(network.http, "_max_json_bytes", 1000)
    network.dns.answers[API_HOST] = [PUBLIC]
    network.net.replies.append(
        reply(200, b"[" + b"0," * 5000 + b"0]", length=False, content_type="application/json")
    )
    out = await call_tool("get_record", id_or_reference="C8853102")
    assert out["error"] == "too_large"


async def test_a_declared_size_too_large_is_refused_before_reading(network, monkeypatch):
    monkeypatch.setattr(network.http, "_max_json_bytes", 1000)
    network.dns.answers[API_HOST] = [PUBLIC]
    network.net.replies.append(reply(200, b"[" + b"0," * 5000 + b"0]"))
    out = await call_tool("get_record", id_or_reference="C8853102")
    assert out["error"] == "too_large"


def test_proxies_in_the_environment_are_not_used(monkeypatch, tmp_path):
    """Through a proxy, the proxy would choose the address the check was meant to."""
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.1:3128")
    http = DiscoveryHttp(tmp_path / "state")
    assert http._http._mounts == {}
