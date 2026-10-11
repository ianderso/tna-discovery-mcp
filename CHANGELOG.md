# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/). The tool surface is the public
interface: renaming or removing a tool or a parameter is a major release, and
adding one is a minor release. Before 1.0, a minor release may do either.

## [Unreleased]

## [0.1.0] — 2026-10-11

First release.

### Added

- Five read-only tools over the UK National Archives' Discovery API:
  `search_records`, `get_record`, `browse`, `find_soldier` and
  `budget_status`.
- `search_records` with series, department, covering-date and holder filters
  (TNA, other archives, or one archive by Archon code), a `digitised` flag per
  hit, and counts by holder, archive and century. Dates are sent as full ISO
  dates, because Discovery answers a bare year with a 500.
- `get_record` by id or exact reference, with every field Discovery gives,
  the record's hierarchy and series title, where the record can be read, and
  a citation (holder and reference).
- `browse` one level down a series, sub-series or piece, with a cursor that
  does not repeat the record a page starts from.
- A parser for WO 97's standard description (name, aliases, birthplace,
  county, regiments, discharge age and year, service years, estimated birth
  year, the original text kept), applied in every tool that meets a WO 97
  item, and `find_soldier`, a WO 97 search filtered by surname or alias,
  forename, discharge years, regiment and birthplace, which says what it read
  and why it set men aside.
- TNA's terms built in: one request at a time at least a second apart; a
  daily budget of 3,000 requests, counted per request in a ledger shared by
  sessions, refusing with `budget_spent` when spent; and no cache of anything
  the API returns.
- One host, `discovery.nationalarchives.gov.uk`, enforced by a request hook;
  every connection checked where it is made against private, loopback,
  link-local, CGNAT, multicast, reserved and unspecified addresses; redirects
  only on that host; answers capped at 10 MB as they stream.
