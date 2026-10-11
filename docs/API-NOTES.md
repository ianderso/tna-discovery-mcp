# Discovery API notes

What TNA's Discovery API actually does, observed against the live service.
TNA documents it in a Swagger sandbox at
<https://discovery.nationalarchives.gov.uk/API/sandbox/index>, whose
specification is at `/API/v1/docs`; several things below differ from it.

Observed 2026-10-11, about sixty requests in all, at least 1.2 seconds apart,
with this project's User-Agent and no sign-in.

## Transport

- `https://discovery.nationalarchives.gov.uk/API/...`. No key, no account, no
  cookie. Served by IIS behind CloudFront; no bot check was met.
- **Ask for JSON** with `Accept: application/json`; the API also speaks XML.
- **JSON keys are camelCase** (`records`, `count`, `citableReference`), though
  the specification writes them in PascalCase (`Records`, `Count`).
- Every route has a `/v1/` form and an unversioned twin. The server uses the
  `/v1/` forms.
- Responses took 0.15 to 1.0 s, once 5.2 s. No rate limit was met, and no
  `Retry-After` or rate-limit header was seen.
- **`robots.txt`** disallows `/browse/`, `/results`, `/SearchUI`, `/image/`,
  `/details/addtobasket` and some other website paths; it does not mention
  `/API/`.

## Failures

| Situation | Answer |
| --- | --- |
| `records/v1/details/{id}` for an id that does not exist | `204 No Content`, empty body |
| An id in the wrong case (`c8853102`) | `204`: ids are case-sensitive |
| `records/v1/collection/{reference}` for a reference nobody uses | 200, `{"assets": [], ...}` |
| A reference in the wrong case (`wo 97/1211/256`) | 200, empty `assets`: references are case-sensitive |
| `sps.dateFrom=1830` (a bare year) | **500**, `text/html`, TNA's "Internal Server Error" page |
| `sps.dateFrom=notadate` | 500, the same page |

A bad argument can therefore look like an outage. The server sends only full
ISO dates (`1831-01-01`), validated first.

## Search: `GET /API/search/v1/records`

- `sps.searchQuery` is documented as required but may be left out when a
  filter is given; `*` matches everything (`sps.departments=WO` with `*`
  counted 10,017,768).
- Several words are ANDed: `james hargreaves` in WO 97 found 3 of the 30
  `hargreaves` hits. A trailing `*` matches word beginnings (`hargr*` found 64,
  including a birthplace HARGRAVE). Words match whole: `hargreaves` finds
  "JAMES HARGRAVES alias JAMES HARGREAVES" but not a man written only as
  HARGRAVES.
- `sps.recordSeries=WO 97`, `sps.departments=WO`, `sps.heldByCode=TNA|OTH|ALL`
  and `sps.recordRepositories=182` (an Archon code) all filter as named.
- **`sps.dateFrom` / `sps.dateTo` select overlap.** WO 97 `atkinson` with
  1830-01-01 to 1834-12-31 returned men whose covering dates were 1811-1835,
  1822-1844 and 1830-1834: any range that touches the window.
- **Pages are 1-based**: `sps.page=0` and `sps.page=1` return the same page.
  `sps.resultsPageSize` is at most 1,000 (default 15), and page times size may
  not pass 10,000. A page of 500 WO 97 hits was 0.5 MB.
- **Relevance ties are not stable between requests.** Three requests for pages
  0, 1 and 2 of five `hargreaves` hits, sorted by relevance, repeated records
  across pages. Sorted by `REFERENCE_ASCENDING` the pages were disjoint.
- The person fields (`sps.lastName`, `sps.firstName`) do not apply to WO 97:
  `sps.lastName=atkinson` with the series found 0.
- Each hit has `id`, `reference`, `title`, `description`, `coveringDates`,
  `numStartDate`/`numEndDate` (`18110101`), `heldBy` (names as strings),
  `context` (the hierarchy as one sentence), `catalogueLevel`, `source`,
  `places`, `department` and more. **`title` is cut at about 100 characters**
  with `...`; `description` is whole.
- **There is no digitised flag in a hit.** `source` says where the description
  came from: `100` TNA's catalogue, `200` TNA's digitised records, `300` the
  National Register of Archives, `600` another archive's catalogue. Digitised
  war diaries (WO 95) and wills (PROB 11) are `200`; WO 97 is `100`. The
  server sets a hit's `digitised` from `source == "200"`; `get_record` has
  TNA's own `digitised` flag.
- Facets come with every search: `heldByReps`, `repositories` (each code is
  the Archon number, a space, and the archive's name),
  `timePeriods` (centuries), `sources`.

## Records

- **`records/v1/details/{id}`** gives every field (the specification's
  `InformationAssetViewModel`). Text fields hold EAD markup: `<scopecontent>`,
  `<p>`, `<head>`, `<list><item>`, `<extref href=...>`, `<emph altrender=...>`,
  `<persname>`. Some titles carry an entity with no semicolon:
  `<unittitle type=&#34Title">`. A digitised will's description is all markup:
  `<emph altrender="doctype">W</emph><persname><emph
  altrender="forenames">Josia</emph>...`.
- A WO 97 item's description is one `<p>` per part: `JOHN ATKINSON`, `Born
  MANCHESTER, Lancashire`, `Served in Royal Artillery`, `Discharged aged 41`,
  and sometimes `Covering date gives year of discharge.` The same text, joined,
  is a search hit's `description`.
- **`records/v1/context/{id}`** lists the ancestors, archive first, then
  department, division, series, sub-series, piece, and the record itself last.
  Levels are numbered 1 (department) to 7 (item); the archive node is level 0
  with `source: "Archon"`. A piece has no title, only a scope note
  ("Royal Artillery: And - Ayt").
- **`records/v1/collection/{reference}`** finds records by citable reference,
  with the slashes percent-encoded (`WO%2097%2F1211%2F256`); it can return
  several when other archives use the same reference.
- **`records/v1/children/{parentId}`** lists children in catalogue order,
  `limit` 1 to 500 (default 30). `hasMoreAfterLast` says whether more follow.
  To continue, pass the last child's `sortKey` as `batchStartMark` with
  `direction=NEXT`: **the page starts with that record again**, whatever
  `includeCursor` says, so the server asks for one more and drops it.
- Ids: TNA's records are `C` and digits (`C8853102`), digitised records `D` and
  digits or a 32-character hex string, Archon entries `A` and digits, NRA
  entries `N` and digits, and other archives' records GUIDs.

## WO 97, as described

- WO 97's sub-series (children of `C14305`): 1760-1854, described item by item
  (WO 97/1-1271, `C28938`); 1855-1872 by regiment and range of surname; 1873-1882
  by arm of service and surname; 1883-1900 and 1900-1913 by surname.
- Item descriptions follow `NAME [alias NAME] Born PLACE[, County] Served in
  REGT[; REGT...] Discharged aged N`. Seen variants: `Born AT SEA` with no
  county; `Born AT SEA, England`; `Discharged aged [Not Known]`; `other
  regiment(s) unspecified` as the last regiment; a man with one name; a trailing
  `Covering date gives year of discharge.` or `...year of enlistment.` when
  there is one covering date.
- Covering dates are otherwise the papers' first and last years, usually
  enlistment and discharge.
- `digitised` is false for WO 97 items; the series record's access conditions
  say "Available in digital format unless otherwise stated".

## Terms

Read 2026-10-10 and again 2026-10-11 at
<https://www.nationalarchives.gov.uk/terms-and-conditions/discovery-for-developers-about-the-application-programming-interface-api/>:
the Open Government Licence v3.0; 3,000 calls a day at no more than one a
second "as a guideline"; "please do not cache or store any content returned
by the API"; developers asked to email webmaster@nationalarchives.gov.uk with
the IP address they will call from. The API answered without that email.
