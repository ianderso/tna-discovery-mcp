# tna-discovery-mcp

[![CI](https://github.com/ianderso/tna-discovery-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/ianderso/tna-discovery-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/tna-discovery-mcp)](https://pypi.org/project/tna-discovery-mcp/)

<!-- mcp-name: io.github.ianderso/tna-discovery-mcp -->

An [MCP](https://modelcontextprotocol.io) server for **Discovery, the
catalogue of the UK National Archives** (TNA): more than 37 million
descriptions of the records held at Kew, and the catalogues of more than
2,500 other archives across the UK and beyond, through TNA's keyless
[Discovery API](https://discovery.nationalarchives.gov.uk/API/sandbox/index).

For family historians the catalogue is where a British soldier, a will, a
muster roll or a county record office's papers are first found. One series
gets a tool of its own: **WO 97**, the Royal Hospital Chelsea's soldiers'
service documents, which describes every man discharged to a pension from
1760 to 1854 in one standard sentence ("JOHN ATKINSON Born MANCHESTER,
Lancashire Served in Royal Artillery Discharged aged 41"). `find_soldier`
searches it by name and keeps the men whose regiment, birthplace and
discharge year fit, each parsed into fields with an estimated birth year.

It works the way a careful genealogist does. **A catalogue description is a
finding aid**: it says a record exists and where it is, not what it says.
Images of most series are not free on Discovery. WO 97's are on Findmypast,
and FamilySearch collection 1952868 indexes them. Every result carries the
holding archive, the reference and the record's Discovery page, because the
archive's reference is what gets cited, not this server.

It is the UK counterpart of
[nara-catalog-mcp](https://github.com/ianderso/nara-catalog-mcp). Nothing here
writes anywhere, and nothing here keeps a family tree.

This is an independent project. It is not affiliated with, endorsed by, or
supported by The National Archives.

## Tools

The server publishes five tools. All are read-only.

| Tool | Purpose |
| --- | --- |
| `search_records` | Search the catalogue's descriptions by words, series (`WO 97`), department (`WO`), covering dates, and holder (TNA, other archives, or one archive by Archon code). Each hit has its id, reference, description, covering dates, holder, a `digitised` flag and its page; a WO 97 item is parsed too. Reports counts by holder, archive and century. |
| `get_record` | One description in full, by id or by exact reference (`WO 97/1211/256`): every field Discovery gives, its place in the hierarchy (department, series, piece), where the record can be read, and a citation. A WO 97 item's description is parsed into name, birthplace, county, regiments, discharge age and year, service years and an estimated birth year, keeping the original text. |
| `browse` | The records one level below a series, sub-series or piece, in catalogue order, with a cursor to continue: WO 97's pieces of one regiment's men, WO 12's regiments and their yearly muster books. |
| `find_soldier` | A WO 97 search by surname (a trailing `*` for variants), forename, discharge years, regiment and birthplace, with each match parsed. Says how many descriptions were read and why the rest were set aside. |
| `budget_status` | Today's requests against the daily budget, this session's, and the last error. Makes no request. |

## Setup

You need Python 3.11 or later and [uv](https://docs.astral.sh/uv/). There is
no key to request.

**Without cloning.** `uvx` fetches it from PyPI and runs it in one step:

```bash
uvx tna-discovery-mcp
```

**From a clone**, which is what you want if you will change it:

```bash
git clone https://github.com/ianderso/tna-discovery-mcp
cd tna-discovery-mcp
uv sync
uv run tna-discovery-mcp   # stdio server, usually launched by the client
```

Either way the server speaks MCP over stdio, so you will normally let an MCP
client start it rather than run it by hand.

### Claude Desktop

```json
{
  "mcpServers": {
    "tna-discovery": {
      "command": "uvx",
      "args": ["tna-discovery-mcp"]
    }
  }
}
```

A desktop app does not always inherit your shell's `PATH`. If the server fails
to start because `uvx` cannot be found, give the full path that `which uvx`
prints as the `command`.

### Claude Code

```bash
claude mcp add tna-discovery -- uvx tna-discovery-mcp
```

### TNA asks to hear from you

TNA's API page asks developers to email them, with the IP address requests
will come from: "please contact us via email and include the IP address". The
API answered without it when this server was built, so it is a request, not a
condition of access. Because every user of this server sends requests from
their own address, the request passes to you: if you use the server
regularly, write to **webmaster@nationalarchives.gov.uk** with your IP
address and a line on what you use the API for. TNA also asks for feedback on
the API.

## Configuration

Nothing is required. A `.env` file in the directory the server starts in
supplies anything the environment does not; only that directory is read.

| Variable | Meaning |
| --- | --- |
| `TNA_DISCOVERY_TIMEOUT` | HTTP timeout in seconds for one request. Default 30. |
| `TNA_DISCOVERY_MIN_INTERVAL` | Least seconds between two requests. Default 1, and never below 1: TNA's guideline. |
| `TNA_DISCOVERY_DAILY_BUDGET` | Requests a day (UTC) before every tool refuses with `budget_spent`. Default 3,000, and never above it: TNA's guideline. Set it lower to leave headroom. |
| `TNA_DISCOVERY_CONTACT` | An email address or URL added to the User-Agent, so TNA can reach you if your use causes trouble. Optional, and courteous. |
| `TNA_DISCOVERY_STATE_DIR` | Where the day's call count is kept. Default `~/.local/state/tna-discovery-mcp`. The file holds a date and a number, never anything the API returned. |

An unusable value is reported on the first tool call as a `not_configured`
result naming the variable. There is deliberately no cache directory: see
below.

## TNA's terms, and how the server keeps them

TNA's [terms for the Discovery
API](https://www.nationalarchives.gov.uk/terms-and-conditions/discovery-for-developers-about-the-application-programming-interface-api/)
(read 2026-10-10 and 2026-10-11) say, in brief:

- **Licence.** Catalogue information may be used under the [Open Government
  Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/),
  for personal, educational or commercial use.
- **Pace.** "As a guideline, you should make no more than 3,000 API calls per
  day", at no more than one a second, and TNA "may choose to limit the number
  of API calls more formally". The server sends one request at a time, at
  least a second apart, and counts every request it sends (retries and
  failures included) against a daily budget of 3,000, in a ledger shared by
  every session that uses the same state directory. When the day's budget is
  spent, tools answer `budget_spent` and send nothing until midnight UTC.
  `budget_status` shows the count.
- **No caching.** "Please do not cache or store any content returned by the
  API." The server keeps no cache: nothing the API returns is written to disk
  or kept between calls. Two identical calls in flight at the same moment
  share one request, and that is all. A citation carries the reference and
  the record's page, not a stored copy. This makes every repeat cost a
  request, which is why the budget matters.
- **The IP address and feedback** are requests made with "please"; see
  [TNA asks to hear from you](#tna-asks-to-hear-from-you).
- The terms also bar using TNA's logo without permission and using the API
  for illegal or defamatory purposes, and say TNA gives no technical support
  and does not guarantee availability.

`robots.txt` on `discovery.nationalarchives.gov.uk` disallows the website's
browse, results, search-interface and image paths, among others; it does not
mention `/API/`, which is what this server uses.

**Discovery may be replaced.** In late 2025 TNA launched a beta of a new
catalogue that may in time take over from Discovery. This server reads the
Discovery API only; if Discovery is retired, the server will need a new
client for whatever replaces it.

## How to read what comes back

- **A description is a finding aid.** It tells you a record exists, its
  reference and its dates. The papers themselves say more (a WO 97 discharge
  gives age, height, trade and the reason for discharge) and are what to
  cite. `get_record`'s `images` says where to read them.
- **WO 97's images are not on Discovery.** They are on Findmypast (paid),
  and FamilySearch collection 1952868 indexes them. A record marked
  `digitised` has an image on Discovery itself, reached from its Discovery
  page. This server downloads nothing.
- **Same name is not same man.** WO 97 holds dozens of men of most common
  names. Confirm by regiment, birthplace and dates before joining a record to
  a person.
- **Covering dates are the papers' first and last dates,** usually enlistment
  and discharge. A WO 97 entry with one date says which it is ("Covering date
  gives year of discharge", or "...of enlistment"), and the parsed fields
  follow it. The estimated birth year is the discharge year less the age at
  discharge, give or take one.
- **A date filter selects overlap.** `date_from` and `date_to` keep records
  whose covering dates overlap the range, so a man who served 1811-1835 is in
  a search for 1831-1834. `find_soldier` then keeps only men whose discharge
  year falls in the range.
- **Spellings vary.** Discovery matches the words as written: "hargreaves"
  finds "HARGRAVES alias HARGREAVES" but not a plain "HARGRAVES". Try variants
  and a trailing `*`.
- **Only pensioners are in WO 97.** Men who died in service, or left without
  a pension, are not; neither are officers. WO 97 after 1854 is described by
  box (regiment and range of surnames), not by man, so `find_soldier` finds
  nobody discharged later; `browse` the pieces instead.
- **References are exact.** `WO 97/1211/256`: a department code, a space,
  then series, piece and item. The server tidies case and spacing (`wo97/1211`
  works); anything else is searched for, not guessed.
- **Relevance ties shuffle between pages.** To page through a long result,
  sort by `reference` or `date`.
- **Cite the archive's reference.** `citation.cite_as` is the holder and
  reference ("The National Archives, Kew, WO 97/1211/256"); add the series
  title, the covering dates and where you read the image.

## Deliberately not here

- **Downloading images.** Discovery's own images are fetched through the
  website, and most series' images are elsewhere. The server names where to
  look.
- **Any cache.** TNA asks for none.
- **Other archives' websites.** A record held elsewhere is described in
  Discovery; reading it means that archive's own catalogue or a visit.
- **Working around limits or bot checks.** A challenge is reported as
  `blocked`; a spent budget as `budget_spent`.

## Security

Tool arguments are written by a model, and the model reads text this server
does not control: catalogue descriptions, web pages, other tools' output. The
server assumes that text can steer the model, and limits what a steered model
can make it do.

- **One host.** Every request goes to `https://discovery.nationalarchives.gov.uk/API/`.
  A request hook refuses any other host, including one named in a redirect;
  redirects are followed only on that host.
- **Public addresses only, checked where the connection is made.** A name
  that leads to a private, loopback, link-local, CGNAT, multicast, reserved or
  unspecified address, IPv4 or IPv6, is refused, and the connection goes to
  the address that was checked, so DNS rebinding gains nothing. Proxy
  settings in the environment are not used.
- **Arguments are narrowed** before they reach a request: ids by pattern,
  series and department codes by pattern, dates to full ISO dates, a
  reference percent-encoded as one path segment, search words only ever as a
  query parameter.
- **Bounded answers.** An answer over 10 MB is refused as it streams in.
- **No writes but one.** The only file is the day's call count.
- **Catalogue text is untrusted.** Descriptions reach the model verbatim. The
  server's instructions tell the model to treat that text as material to
  weigh, never as instructions; the model still decides, so review what it
  proposes to do.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Development

```bash
uv sync --extra dev
uv run pytest                      # mocked with respx; never touches the API
uv run ruff check .
uv run ruff format --check .
uv run python -m tests.live_check  # paced calls to the live API
```

The live check asks Discovery what the recorded fixtures cannot: whether its
answers still have the shape the server reads. See
[CONTRIBUTING.md](CONTRIBUTING.md) for how the suite is organised,
[docs/API-NOTES.md](docs/API-NOTES.md) for what was observed of the API and
when, and [docs/DESIGN.md](docs/DESIGN.md) for why the server is shaped this
way.

## Credits

The catalogue belongs to The National Archives and the archives whose
descriptions it hosts, and is used under the Open Government Licence v3.0:
"Contains public sector information licensed under the Open Government
Licence v3.0."

## License

[MIT](LICENSE).
