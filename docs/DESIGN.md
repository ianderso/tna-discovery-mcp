# Design

Why the server is shaped the way it is, and what is out of scope by decision.

## The question it answers

"Is there a record of this person at the National Archives, and where is it?"
Discovery is the UK's national catalogue: TNA's own records at Kew, and the
catalogues of 2,500 other archives. It answers that question with a
description and a reference, never with the document. For a British soldier
discharged to a pension before 1855 it answers better than for almost anyone
else, because WO 97 describes every such man by name, birthplace, regiments
and age; `find_soldier` exists for that series alone.

It is the UK counterpart of `nara-catalog-mcp`, and borrows its shape: search,
read one record with its hierarchy, walk down from a series, and a budget
tool in place of a cache report.

## Five tools

- **`search_records`** is the general search, with the filters a researcher
  uses: series, department, covering dates, and holder (TNA, other archives,
  or one archive by Archon code). Each hit carries what a citation needs and,
  for a WO 97 item, the parsed description, so a search is often enough.
- **`get_record`** reads one description in full. It takes an id or an exact
  reference, because a citation gives a reference; the reference costs one
  more request. With its hierarchy (one more request) it names the series
  title, which is what a citation wants after the reference.
- **`browse`** walks one level down from a series, sub-series or piece, with a
  cursor. It answers "what else is in this box?" and lists WO 12's muster
  books by regiment and year. For one regiment in one year, a search is
  quicker, and the description says so.
- **`find_soldier`** is a WO 97 search that parses and filters: the name
  search runs at Discovery, the filters (exact surname or alias, forename,
  discharge year, regiment, birthplace) run here on up to 500 descriptions a
  page. It reports what it read and why it set men aside, so a negative is
  bounded.
- **`budget_status`** replaces the siblings' `cache_status`: there is no cache
  to report, and a budget to keep.

The spec's `list_pieces(series, regiment?, year?)` became `browse` plus a
search with `series`: the hierarchies of WO 12, WO 17 and WO 25 differ, and
search already filters pieces by regiment words and dates.

## Terms that shape the code

TNA's terms (see the README) ask three things of developers, and the server
builds each in rather than leaving it to the user:

- **One request a second.** The client sends one request at a time, at least
  `TNA_DISCOVERY_MIN_INTERVAL` apart, and the setting cannot go below 1.
- **3,000 requests a day.** Every request sent (retries and failures
  included) is counted in a ledger in `TNA_DISCOVERY_STATE_DIR`, per UTC day,
  shared by every session using the directory. Once the day's budget is
  spent, the client sends nothing and each tool answers `budget_spent`. The
  setting may lower the budget, never raise it. The ledger holds a date and a
  count, nothing the API returned. Two servers writing at the same instant
  can lose a count; the session's own count is the floor, so even an
  unwritable ledger holds one session to the budget.
- **No caching or storing of content.** No answer is written anywhere, and
  none is kept between calls. Identical calls in flight at the same moment
  share one request (that saves TNA a request, and keeps nothing), and that is
  the only reuse. A result points at the record's Discovery page and carries
  its reference, so a citation never depends on a stored copy.

The request that each developer email TNA with their IP address is passed on
in the README to each user, since each user's address differs.

## The evidence model

- **A description is a finding aid.** Every tool's description, and the
  server's instructions, say so. `get_record` adds `images`: for WO 97, that
  the images are on Findmypast and FamilySearch collection 1952868 indexes
  them; for a digitised record, that its image is reached from its page; for
  anything else, that the original is with the archive.
- **Cite the archive's reference.** `citation.cite_as` is the holder and the
  reference; the series title, covering dates and page address come with it.
- **Same name is not same man.** `find_soldier` says it in its description and
  its result, and gives the fields (regiment, birthplace, dates) to confirm by.
- **A negative is bounded.** A zero carries a note on what it covers:
  descriptions only, the words as written, many series described only by
  box.

## Parsing WO 97

The 1760-1854 part of WO 97 is described item by item in one sentence:
`NAME [alias NAME] Born PLACE[, County] Served in REGT[; REGT] Discharged
aged N`. The parser splits on the markers with their capitals (names and
places are in upper case, so a place called BORNHOLM is not a `Born`), keeps
aliases, splits regiments on `;`, flags "other regiment(s) unspecified", and
reads an unknown age as unknown. Covering dates give service years and the
discharge year, unless the description says its one date is the year of
discharge or of enlistment. The estimated birth year is the discharge year
less the age, and the range one either side of it. The original sentence is
always kept, because the parse is a convenience and the description is what
is cited.

Matching is deliberately loose: a regiment matches when every word asked for
is in one regiment the man served in (ordinals and plurals folded, so "33rd
Regiment of Foot" finds "33rd Foot Regiment"); a birthplace when every word is
in the place or county. A filter that drops the right man is worse than one
that keeps a stranger.

## Which host a tool reaches

One: `discovery.nationalarchives.gov.uk`, over https. A request hook refuses
any other host, including an address taken from a response; redirects are
followed by hand on that host only. The transport resolves the host itself,
refuses a non-public address, and connects to the address it checked, so a
redirect, a retry or a rebinding name is checked again. Proxy settings in the
environment are not used. Every argument is narrowed before it reaches a
request: ids and codes by pattern, dates to full ISO dates (Discovery answers
a bare year with a 500), references percent-encoded as one path segment,
search words only as a query parameter. Answers are capped at 10 MB as they
stream.

## Out of scope, by decision

- **Images.** Discovery's own digitised images are fetched through its
  website; WO 97's are on Findmypast. The server names where to look.
- **A cache.** TNA asks for none.
- **The file-authority and repository routes** (`/fileauthorities`,
  `/repository`, `/search/archives`). Useful for archive-finding, which
  `snac-archives-mcp` covers; they can be added if a research need appears.
- **TNA's beta catalogue.** Launched in late 2025, it may replace Discovery.
  When it publishes an API, a client for it can sit behind the same tools.
- **Working around limits or bot checks.** A challenge is reported as
  `blocked`, a spent budget as `budget_spent`.

## Tests

- Everything is mocked with respx against **recorded** answers
  (`tests/fixtures/`, historical records only, trimmed). The suite never
  touches the live API.
- Contract tests pin the tool surface: names and parameters (snapshot),
  descriptions present, dedented and within a budget, the pitfalls present,
  annotations, no tool that raises when Discovery fails or answers in an
  unexpected shape, unknown parameters refused.
- `tests/test_client.py` covers pacing, the budget (counted per request,
  shared through the ledger, reset by day, held without the ledger), the
  absence of any cache, retries and refusals.
- `tests/test_security.py` takes the attacker's side: references that try to
  leave their path segment, a name that leads to a private address, a
  rebinding name, a redirect off the host, an answer too large.
- `tests/live_check.py` calls the live API by hand.
