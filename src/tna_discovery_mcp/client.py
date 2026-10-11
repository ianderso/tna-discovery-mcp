"""Polite, uncached async HTTP for Discovery's API.

Discovery is The National Archives' catalogue, and its API is a shared public
service offered as a beta. The client is a careful guest:

* **One host.** A request hook refuses anything but https to
  ``discovery.nationalarchives.gov.uk``, including an address taken from a
  response. Redirects are followed by hand, and only on that host; anything
  else is reported, never followed.
* **Only public addresses, checked where the connection is made.** The
  transport looks the host up itself, refuses it if any address is private,
  loopback, link-local, shared (CGNAT), multicast, reserved or unspecified,
  and connects to the address it checked. A redirect or a retry is a new
  connection and is checked again, so a name that changes its answer between
  two lookups (DNS rebinding) gains nothing.
* **Bounded answers.** An answer over ``MAX_JSON_BYTES`` is refused as it
  streams in, before it is all read.
* **One request at a time, at least ``min_interval`` apart.** TNA's terms
  ask for no more than one request a second, so the interval never goes below
  that.
* **A daily budget.** TNA's terms give 3,000 calls a day as a guideline.
  Every request sent is counted, retries and failures included, in a small
  ledger file holding the day and the count; once the day's budget is spent,
  nothing more is sent until the next day (UTC) and each call fails with
  ``budget_spent``.
* **No cache.** TNA's terms ask developers not to cache or store what the
  API returns, so nothing it returns is written anywhere. Identical calls in
  flight at the same moment share one request; that is all.
* **A 429, a 5xx or a dropped connection gets one retry,** honouring
  ``Retry-After`` up to 30 seconds. A timeout is not retried: a server that
  took that long is struggling already.
* **An honest User-Agent** naming the package, its version and its home.

Discovery answers a record id it does not know with ``204 No Content``, and
some malformed requests (a date that is not a full ISO date) with a 500 and an
HTML page; :func:`decode` and the server's argument checks deal with both.
"""

from __future__ import annotations

import asyncio
import email.utils
import ipaddress
import json
import logging
import os
import random
import socket
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

import httpcore
import httpx

from . import __version__

logger = logging.getLogger("tna_discovery_mcp.client")

#: Where the project lives; named in the User-Agent so TNA can see who calls.
PROJECT_URL = "https://github.com/ianderso/tna-discovery-mcp"

#: The one host any request may reach.
API_HOST = "discovery.nationalarchives.gov.uk"

#: Every request starts here.
API_BASE = f"https://{API_HOST}/API"

#: Longest wait honoured from a ``Retry-After`` header, in seconds.
RETRY_AFTER_CAP = 30.0

#: Redirect hops followed on the one host.
MAX_REDIRECTS = 3

#: An answer larger than this is refused. A search page of 500 soldiers'
#: descriptions, the largest any tool asks for, was 0.5 MB on 2026-10-11.
MAX_JSON_BYTES = 10_000_000

#: The ledger holding the day's call count, inside the state directory. It
#: holds a date and a number, never anything the API returned.
BUDGET_FILE = "budget.json"

#: Shared address space for carrier-grade NAT, which ``ipaddress`` marks
#: neither private nor global on every supported Python.
_SHARED = ipaddress.ip_network("100.64.0.0/10")

#: NAT64's well-known prefix: its last 32 bits are an IPv4 address.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

Params = Sequence[tuple[str, str]]


def today_utc() -> str:
    """The day the budget is counted in, as ``YYYY-MM-DD`` (UTC).

    TNA does not say which clock its guideline uses. London is UTC or an hour
    ahead of it, so the boundary is off by an hour at most.
    """
    return datetime.now(UTC).strftime("%Y-%m-%d")


class DiscoveryError(RuntimeError):
    """A request Discovery refused, or one that could not be completed.

    ``code`` says what kind of failure it was: ``no_response`` and
    ``timeout`` (``status`` 0), ``http_error``, ``rate_limited``,
    ``not_json``, ``not_found`` (a 204, Discovery's answer to an unknown id),
    ``redirected`` (``location`` set), ``challenge`` (a bot check),
    ``too_large``, or ``budget_spent`` (nothing was sent).
    """

    def __init__(
        self, code: str, detail: str, *, status: int = 0, url: str = "", location: str = ""
    ):
        """Record what failed and where."""
        self.code = code
        self.detail = detail
        self.status = status
        self.url = url
        self.location = location
        super().__init__(f"{url} -> {code} {status or ''}: {detail}".strip())


class HostNotAllowed(RuntimeError):
    """Raised when a request is aimed anywhere but Discovery's API host."""


class PrivateAddress(HostNotAllowed):
    """Raised at connect time when the host's name leads to a non-public address."""


def user_agent(contact: str = "") -> str:
    """The User-Agent sent with every request, naming this project."""
    extra = f"; {contact}" if contact else ""
    return f"tna-discovery-mcp/{__version__} (+{PROJECT_URL}{extra})"


def address_problem(address: str) -> str | None:
    """Why a connection must not go to this IP address, or None if it may.

    Refused, in IPv4 and IPv6: loopback, private, link-local, shared (CGNAT),
    multicast, reserved, unspecified and site-local addresses, anything else
    not globally routable, and an IPv6 address that carries one of those as
    an embedded IPv4 address (IPv4-mapped, 6to4, NAT64).
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return "unreadable"
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return "IPv4-mapped"
        embedded = ip.sixtofour
        if embedded is None and ip in _NAT64:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFF_FFFF)
        if embedded is not None and (problem := address_problem(str(embedded))):
            return problem
    checks = (
        ("loopback", ip.is_loopback),
        ("unspecified", ip.is_unspecified),
        ("link-local", ip.is_link_local),
        ("multicast", ip.is_multicast),
        ("private", ip.is_private),
        ("shared (CGNAT)", ip.version == 4 and ip in _SHARED),
        ("reserved", ip.is_reserved),
        ("site-local", ip.version == 6 and ip.is_site_local),
        ("non-global", not ip.is_global),
    )
    return next((name for name, hit in checks if hit), None)


class PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """A network backend that connects only to public addresses.

    It resolves the host itself, refuses the connection if any address the
    name gives is not public, and then connects to an address it checked,
    never to the name, so the name cannot answer differently in between.
    TLS still verifies the certificate against the host name.
    """

    def __init__(self, inner: httpcore.AsyncNetworkBackend):
        """Wrap the backend that makes the actual connections."""
        self._inner = inner

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Look ``host`` up, check every address, and connect to a checked one."""
        addresses = await _look_up(host, port, timeout)
        for address in addresses:
            if problem := address_problem(address):
                logger.warning("refusing %s: it resolves to %s (%s)", host, address, problem)
                raise PrivateAddress(
                    f"refusing to connect to {host}: it resolves to an address that is not "
                    f"public ({problem}), so it is not The National Archives' site"
                )
        error: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error or httpcore.ConnectError(f"cannot connect to {host}")

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Iterable[Any] | None = None
    ) -> httpcore.AsyncNetworkStream:
        """Refuse: the API is reached over TCP."""
        raise HostNotAllowed("refusing a connection to a local socket")

    async def sleep(self, seconds: float) -> None:
        """Defer to the wrapped backend."""
        await self._inner.sleep(seconds)


async def _look_up(host: str, port: int, timeout: float | None) -> list[str]:
    """Every address ``host`` resolves to, in the resolver's order."""
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout
        )
    except TimeoutError:
        raise httpcore.ConnectTimeout(f"looking up {host} took too long") from None
    except OSError as exc:
        raise httpcore.ConnectError(f"cannot look up {host}: {exc}") from None
    addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses:
        raise httpcore.ConnectError(f"{host} has no address")
    return addresses


class PublicOnlyTransport(httpx.AsyncHTTPTransport):
    """httpx's own transport, connecting through :class:`PublicOnlyBackend`.

    httpx takes no network backend as an argument, so the one its connection
    pool made is wrapped in place. Should a future httpx or httpcore move it,
    construction fails rather than run without the check.
    """

    def __init__(self, *, backend: httpcore.AsyncNetworkBackend | None = None, **kwargs: Any):
        """Build the transport; ``backend`` replaces the real network, for tests."""
        super().__init__(**kwargs)
        pool = getattr(self, "_pool", None)
        inner = getattr(pool, "_network_backend", None)
        if not isinstance(pool, httpcore.AsyncConnectionPool) or not isinstance(
            inner, httpcore.AsyncNetworkBackend
        ):
            raise RuntimeError(
                "httpx's connection pool has changed shape; the public-address check "
                "cannot be installed, so no request will be sent"
            )
        pool._network_backend = PublicOnlyBackend(backend or inner)


class DiscoveryHttp:
    """Paced, budgeted async HTTP for Discovery's API. Nothing is cached.

    Parameters
    ----------
    state_dir : Path
        Directory for the day's call count. Created on first write.
    timeout : float, optional
        Per-request timeout in seconds.
    min_interval : float, optional
        Least time between the start of one request and the next.
    daily_budget : int, optional
        Requests a day before every call fails with ``budget_spent``.
    contact : str, optional
        Appended to the User-Agent.
    retries : int, optional
        Further attempts after a 429, a 5xx or a dropped connection.
    backoff : float, optional
        Base of the wait between attempts when no ``Retry-After`` is given.
    max_json_bytes : int, optional
        Largest answer read.
    transport : httpx.AsyncBaseTransport, optional
        For tests. The default is a :class:`PublicOnlyTransport`. httpx does
        not apply proxy settings from the environment to a transport it is
        given, which suits the check: through a proxy, the proxy would choose
        the address.
    today : callable, optional
        Returns the budget's day as text; for tests.
    """

    def __init__(
        self,
        state_dir: Path,
        *,
        timeout: float = 30.0,
        min_interval: float = 1.0,
        daily_budget: int = 3_000,
        contact: str = "",
        retries: int = 1,
        backoff: float = 1.0,
        max_json_bytes: int = MAX_JSON_BYTES,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        today: Callable[[], str] = today_utc,
    ):
        self._state_dir = state_dir
        self._timeout = timeout
        self._min_interval = min_interval
        self._daily_budget = daily_budget
        self._retries = retries
        self._backoff = backoff
        self._clock = clock
        self._sleep = sleep
        self._today = today
        self._max_json_bytes = max_json_bytes
        self._http = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": user_agent(contact), "Accept": "application/json"},
            event_hooks={"request": [self._only_the_api_host]},
            follow_redirects=False,
            transport=transport or PublicOnlyTransport(),
        )
        self._lock = asyncio.Lock()
        self._last: float | None = None
        self._inflight: dict[str, asyncio.Future] = {}
        self._live_calls = 0
        self._shared_waits = 0
        self._last_error: dict | None = None
        # The session's own count for the day: the floor under the ledger's,
        # so the budget holds even where the ledger cannot be written.
        self._session_day = ""
        self._session_day_calls = 0

    # ------------------------------------------------------------------ #
    # Counters
    # ------------------------------------------------------------------ #
    @property
    def live_calls(self) -> int:
        """int: Requests sent this session, retries and failures included."""
        return self._live_calls

    @property
    def shared_waits(self) -> int:
        """int: Calls answered by joining an identical request already in flight."""
        return self._shared_waits

    @property
    def last_error(self) -> dict | None:
        """dict or None: The most recent failure this session."""
        return self._last_error

    @property
    def daily_budget(self) -> int:
        """int: Requests a day before calls are refused."""
        return self._daily_budget

    @property
    def min_interval(self) -> float:
        """float: Least seconds between two requests."""
        return self._min_interval

    @property
    def ledger_path(self) -> Path:
        """Path: The file holding the day's call count."""
        return self._state_dir / BUDGET_FILE

    def day_ledger(self) -> tuple[str, int]:
        """The budget's day and the requests counted against it.

        Read from the ledger on every call, so a second server sharing the
        state directory is seen as soon as it writes. A missing, corrupt or
        earlier day's ledger reads as zero, and the session's own count for
        the day is the floor.
        """
        day = self._today()
        count = 0
        try:
            data = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            data = None
        if isinstance(data, dict) and data.get("day") == day:
            value = data.get("calls")
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                count = value
        if self._session_day == day:
            count = max(count, self._session_day_calls)
        return day, count

    def _spend_one(self) -> None:
        """Count one request against the day, or refuse it if the day is spent.

        The ledger is read, incremented and replaced atomically. Two servers
        sharing one state directory can read the same value and both write
        it plus one, losing a count per collision; that undercount is small
        and ``budget_status`` says so.
        """
        day, count = self.day_ledger()
        if count >= self._daily_budget:
            raise DiscoveryError(
                "budget_spent",
                f"this server's daily budget of {self._daily_budget:,} requests is spent for "
                f"{day} (UTC); nothing was sent",
            )
        if self._session_day != day:
            self._session_day, self._session_day_calls = day, 0
        self._session_day_calls = count + 1
        self._live_calls += 1
        try:
            _write_atomically(
                self.ledger_path,
                json.dumps(
                    {
                        "day": day,
                        "calls": count + 1,
                        "updated": datetime.now(UTC).isoformat(timespec="seconds"),
                    }
                ),
            )
        except OSError:
            # The session still counts; only other sessions miss this call.
            logger.warning("could not update the call count at %s", self.ledger_path)

    # ------------------------------------------------------------------ #
    # Lifecycle and the host allowlist
    # ------------------------------------------------------------------ #
    async def aclose(self) -> None:
        """Close the HTTP transport."""
        await self._http.aclose()

    async def __aenter__(self) -> DiscoveryHttp:
        """Return the client."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Close the transport."""
        await self.aclose()

    async def _only_the_api_host(self, request: httpx.Request) -> None:
        """Refuse any request that is not https to Discovery's API host."""
        host = request.url.host.lower()
        if request.url.scheme != "https" or host != API_HOST:
            raise HostNotAllowed(
                f"refusing a request to {host!r}: this server reaches only {API_HOST}"
            )

    # ------------------------------------------------------------------ #
    # Requests
    # ------------------------------------------------------------------ #
    async def get_json(self, path: str, params: Params = ()) -> Any:
        """GET one API path, decoded; shared with an identical call in flight.

        Parameters
        ----------
        path : str
            Everything after ``/API``, starting with ``/``, already
            percent-encoded.
        params : sequence of (str, str)
            Query parameters, in order; a name may repeat.

        Raises
        ------
        DiscoveryError
            For any failure, ``budget_spent`` and ``not_found`` included.
        HostNotAllowed
            Never, for a path; kept for a redirect gone astray.
        """
        url = API_BASE + path
        if params:
            url += "?" + urlencode(list(params))
        return await self._shared(url, lambda: self._fetch_json(url))

    async def _fetch_json(self, url: str) -> Any:
        response = await self._send(url)
        try:
            return decode(response)
        except DiscoveryError as exc:
            self._note(exc)
            raise

    async def _send(self, url: str) -> httpx.Response:
        """One GET, paced, budgeted, retried and redirected by hand; the final response.

        Raises
        ------
        DiscoveryError
            On a status of 400 or more, no response, a bot challenge, a
            redirect off the host, a body over the cap (``too_large``), or a
            spent budget (``budget_spent``, never retried).
        HostNotAllowed
            If the host's name leads to an address that is not public. Never
            retried.
        """
        attempt = 0
        while True:
            try:
                response = await self._follow(url)
            except DiscoveryError as exc:
                if exc.code == "budget_spent":
                    self._note(exc)
                    raise
                error = exc
                response = None
            else:
                if response.status_code < 400:
                    return response
                error = _http_error(response, url)
            retryable = error.code in ("no_response", "rate_limited") or error.status >= 500
            if not retryable or attempt >= self._retries:
                self._note(error)
                raise error
            attempt += 1
            wait = _retry_after(response)
            if wait is None:
                wait = self._backoff * 2 ** (attempt - 1) + random.uniform(0, self._backoff / 2)
            wait = min(wait, RETRY_AFTER_CAP)
            logger.info("%s -> %s; retry %d in %.1fs", url, error.code, attempt, wait)
            await self._sleep(wait)

    async def _follow(self, url: str) -> httpx.Response:
        """Send, following redirects only on the API host."""
        for _ in range(MAX_REDIRECTS + 1):
            response = await self._paced(url)
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = urljoin(url, response.headers.get("location", ""))
            target = urlsplit(location)
            if target.scheme != "https" or (target.hostname or "").lower() != API_HOST:
                raise DiscoveryError(
                    "redirected",
                    f"Discovery redirects this request to {location}",
                    status=response.status_code,
                    url=url,
                    location=location,
                )
            url = location
        raise DiscoveryError("redirected", "too many redirects", url=url)

    async def _paced(self, url: str) -> httpx.Response:
        """Send one request once its turn, its interval and the budget allow.

        The body is streamed and refused as soon as it passes the cap,
        decoded, so neither a declared nor an undeclared size can make the
        server read more.
        """
        async with self._lock:
            if self._last is not None:
                wait = self._min_interval - (self._clock() - self._last)
                if wait > 0:
                    await self._sleep(wait)
            self._spend_one()
            self._last = self._clock()
            try:
                async with self._http.stream("GET", url) as response:
                    body = await _read_capped(response, self._max_json_bytes, url)
                return _with_body(response, body)
            except httpx.TimeoutException as exc:
                raise DiscoveryError("timeout", _transport_text(exc), url=url) from None
            except httpx.TransportError as exc:
                raise DiscoveryError("no_response", _transport_text(exc), url=url) from None

    # ------------------------------------------------------------------ #
    # Shared machinery
    # ------------------------------------------------------------------ #
    async def _shared(self, key: str, make: Callable[[], Awaitable[Any]]) -> Any:
        """Run ``make`` once for concurrent callers asking the same thing.

        This is the only reuse of an answer: it lasts as long as the request
        is in flight, and nothing is kept after it.
        """
        if (pending := self._inflight.get(key)) is not None:
            self._shared_waits += 1
            return await asyncio.shield(pending)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            data = await make()
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as exc:
            future.set_exception(exc)
            # Mark it retrieved: a failure nobody else was waiting on must
            # not be logged as "exception was never retrieved".
            future.exception()
            raise
        else:
            future.set_result(data)
            return data
        finally:
            self._inflight.pop(key, None)

    def _note(self, error: DiscoveryError) -> None:
        self._last_error = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "error": error.code,
            "status": error.status or None,
            "detail": error.detail[:300],
            "request": error.url[:300],
        }


def decode(response: httpx.Response) -> Any:
    """Decode a 2xx answer.

    Observed 2026-10-11: an unknown record id answers ``204 No Content``;
    a reference nobody uses answers 200 with an empty ``assets`` list, which
    is left to the caller.
    """
    url = str(response.url)
    if response.status_code == 204 or not response.content:
        raise DiscoveryError(
            "not_found",
            "Discovery has no record with this id",
            status=response.status_code,
            url=url,
        )
    try:
        return response.json()
    except ValueError:
        text = response.text
        raise DiscoveryError(
            "not_json",
            "Discovery answered with something that is not JSON"
            + (" (a web page)" if text.lstrip()[:1] == "<" else ""),
            status=response.status_code,
            url=url,
        ) from None


async def _read_capped(response: httpx.Response, limit: int, url: str) -> bytes:
    """Read a streamed body, refusing it once it passes ``limit`` bytes."""
    too_large = DiscoveryError(
        "too_large",
        f"the answer is over {limit / 1_000_000:g} MB, more than this server reads",
        status=response.status_code,
        url=url,
    )
    declared = response.headers.get("content-length", "").strip()
    if declared.isdigit() and int(declared) > limit:
        raise too_large
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > limit:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


def _with_body(response: httpx.Response, body: bytes) -> httpx.Response:
    """A complete response carrying ``body``, already decoded, in place of the stream."""
    spent = {"content-encoding", "content-length", "transfer-encoding"}
    return httpx.Response(
        response.status_code,
        headers=[(k, v) for k, v in response.headers.multi_items() if k.lower() not in spent],
        content=body,
        request=response.request,
        extensions=response.extensions,
    )


def _http_error(response: httpx.Response, url: str) -> DiscoveryError:
    """Classify a 4xx or 5xx answer."""
    status = response.status_code
    if response.headers.get("cf-mitigated", "").lower() == "challenge":
        return DiscoveryError(
            "challenge",
            "Discovery answered with a bot check; it must be opened in a browser",
            status=status,
            url=url,
        )
    if status == 429:
        return DiscoveryError(
            "rate_limited", "Discovery asked for fewer requests", status=status, url=url
        )
    text = response.text.strip()
    if text[:1] == "<":
        detail = response.reason_phrase or "an HTML error page"
    else:
        detail = " ".join(text.split())[:300] or response.reason_phrase
    return DiscoveryError("http_error", detail, status=status, url=url)


def _transport_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}".rstrip(": ")


def _retry_after(response: httpx.Response | None) -> float | None:
    """Seconds a ``Retry-After`` header asks for, or None if absent or unreadable."""
    if response is None:
        return None
    raw = (response.headers.get("retry-after") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _write_atomically(path: Path, text: str) -> None:
    """Write a file so a reader never sees it half-written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
