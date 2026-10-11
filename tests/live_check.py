"""Ask the live API what the recorded fixtures cannot. Run by hand.

    uv run python -m tests.live_check

About twenty requests, paced by the client itself (one at a time, at least a
second apart) and counted against the day's budget in the configured state
directory, like any other use. The checks:

* the tools still read the answers they were built against: WO 97/1211/256
  (John Atkinson of Manchester, Royal Artillery, discharged aged 41), the WO 97
  series and its sub-series, a muster book in WO 12, a digitised war diary in
  WO 95;
* a search with a bare year still works, because the server sends a full date
  (Discovery answers a bare year with a 500);
* browsing still pages by cursor without repeating the cursor's record;
* find_soldier still finds the discharges a surname search should;
* an unknown id is still a 204, read as not found.

It is not a test module: pytest does not collect it, and CI never runs it,
because the suite must never depend on someone else's server being up.

Exit status 0 if every check passed, 1 if any failed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable

from tna_discovery_mcp import server
from tna_discovery_mcp.client import DiscoveryHttp
from tna_discovery_mcp.config import load_config

#: (tool, arguments, check, what the check means). ``{after}`` in an argument
#: is replaced by the cursor the previous browse returned.
CHECKS: list[tuple[str, dict, Callable[[dict], bool], str]] = [
    (
        "get_record",
        {"id_or_reference": "WO 97/1211/256"},
        lambda r: (
            r["id"] == "C8853102"
            and r["soldier"]["name"] == "JOHN ATKINSON"
            and r["soldier"]["birthplace"] == "MANCHESTER"
            and r["soldier"]["discharge_age"] == 41
            and r["soldier"]["estimated_birth_year"] == 1794
            and r["series"]["title"] == "Royal Hospital Chelsea: Soldiers Service Documents"
        ),
        "a WO 97 reference reads, parses, and sits in its series",
    ),
    (
        "get_record",
        {"id_or_reference": "C14305", "hierarchy": False},
        lambda r: r["reference"] == "WO 97" and r["level_name"] == "series",
        "the WO 97 series record by id",
    ),
    (
        "search_records",
        {
            "query": "atkinson",
            "series": "WO 97",
            "date_from": "1831",
            "date_to": "1834",
            "count": 20,
        },
        lambda r: r["total"] >= 30 and all("soldier" in h for h in r["records"]),
        "a bare year goes as a full date, and every WO 97 hit parses",
    ),
    (
        "find_soldier",
        {"surname": "Atkinson", "discharged_from": 1831, "discharged_to": 1834},
        lambda r: (
            {"WO 97/1211/251", "WO 97/1211/257"} <= {s["reference"] for s in r["soldiers"]}
            and r["matched"] >= 4
            and all(1831 <= (s["discharge_year"] or 0) <= 1834 for s in r["soldiers"])
        ),
        "find_soldier keeps the men discharged 1831-1834",
    ),
    (
        "find_soldier",
        {"surname": "Hargreaves", "regiment": "Royal Artillery"},
        lambda r: (
            r["matched"] >= 4
            and all(any("Artillery" in g for g in s["regiments"]) for s in r["soldiers"])
        ),
        "the regiment filter keeps the gunners",
    ),
    (
        "search_records",
        {"query": '"33rd foot"', "series": "WO 12", "date_from": "1821", "date_to": "1821"},
        lambda r: any(h["reference"] == "WO 12/4812" for h in r["records"]),
        "a regiment's muster book for a year, by search",
    ),
    (
        "browse",
        {"reference_or_id": "WO 97", "limit": 10},
        lambda r: (
            r["parent_id"] == "C14305" and r["children"][0]["description"].startswith("1760-1854")
        ),
        "WO 97's sub-series, by reference",
    ),
    (
        "browse",
        {"reference_or_id": "C28938", "limit": 3},
        lambda r: (
            [c["reference"] for c in r["children"]] == ["WO 97/1", "WO 97/2", "WO 97/3"]
            and bool(r["next_after"])
        ),
        "the 1760-1854 pieces, first page",
    ),
    (
        "browse",
        {"reference_or_id": "C28938", "limit": 3, "after": "{after}"},
        lambda r: [c["reference"] for c in r["children"]] == ["WO 97/4", "WO 97/5", "WO 97/6"],
        "the next page starts after the cursor, not on it",
    ),
    (
        "search_records",
        {"query": "battalion", "series": "WO 95", "count": 5},
        lambda r: any(h["digitised"] for h in r["records"]),
        "digitised war diaries are flagged",
    ),
    (
        "get_record",
        {"id_or_reference": "C99999999999", "hierarchy": False},
        lambda r: r["error"] == "not_found",
        "an unknown id is a 204, read as not found",
    ),
]

#: Checks whose expected answer is a refusal.
REFUSALS = {"an unknown id is a 204, read as not found"}


async def main() -> int:
    cfg = load_config()
    http = DiscoveryHttp(
        cfg.state_dir,
        timeout=cfg.timeout,
        min_interval=cfg.min_interval,
        daily_budget=cfg.daily_budget,
        contact=cfg.contact,
    )
    server.runtime.config = cfg
    server.runtime.http = http
    failed = 0
    after = ""
    for tool, args, check, meaning in CHECKS:
        args = {k: (after if v == "{after}" else v) for k, v in args.items()}
        result = json.loads((await server.mcp.call_tool(tool, args)).content[0].text)
        if tool == "browse" and result.get("next_after"):
            after = result["next_after"]
        try:
            ok = ("error" not in result or meaning in REFUSALS) and bool(check(result))
        except (KeyError, IndexError, TypeError):
            ok = False
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {tool}: {meaning}")
        if not ok:
            print(f"      got: {json.dumps(result)[:400]}")
    status = json.loads((await server.mcp.call_tool("budget_status", {})).content[0].text)
    print(
        f"\nrequests this run: {status['calls_this_session']}; today: {status['calls_today']} "
        f"of {status['daily_budget']}"
    )
    await http.aclose()
    total = len(CHECKS)
    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
