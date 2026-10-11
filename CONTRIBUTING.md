# Contributing

Issues and pull requests are welcome. This file says how the project is put
together and what a change is expected to carry.

## Setting up

```bash
git clone https://github.com/ianderso/tna-discovery-mcp
cd tna-discovery-mcp
uv sync --extra dev
```

Before sending a change, run what CI runs:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

The suite is mocked with [respx](https://lundberg.github.io/respx/) against
recorded Discovery answers. It must never touch the live API: TNA asks for no
more than 3,000 calls a day, and CI should not depend on the service being
up.

## Where things live

| Path | What it holds |
| --- | --- |
| `src/tna_discovery_mcp/server.py` | The tools. Their docstrings and `Field` descriptions *are* the published tool descriptions and schema. |
| `src/tna_discovery_mcp/client.py` | The paced, budgeted, uncached HTTP client, the one-host allowlist, the redirect rule, the public-address check made at connect time, and the size cap. |
| `src/tna_discovery_mcp/shape.py` | Turning answers into results: markup, levels, references and ids, the WO 97 parser, loose matching. |
| `src/tna_discovery_mcp/config.py` | Settings from the environment and `.env`. |
| `docs/API-NOTES.md` | What the API was observed to do, and when. |
| `docs/DESIGN.md` | Why the server is shaped the way it is, and what is out of scope by decision. |
| `tests/fixtures/` | Recorded answers and the tool-schema snapshot. |
| `tests/test_tool_contract.py` | Tests over the tool surface as a client sees it. |
| `tests/test_security.py` | Every refusal against a steered model: paths, addresses, redirects, sizes. |
| `tests/live_check.py` | The one script that talks to the live API, run by hand. Not collected. |

## What a change carries

**A test that fails without it.** Bug fixes especially: reproduce the bug as a
test first.

**Descriptions written for the model.** A tool's docstring is what a model
reads when choosing and calling it. The combined descriptions have a ceiling
(`DESCRIPTION_BUDGET` in `tests/test_tool_contract.py`), because they are sent
on every session. Raise it deliberately, in a pull request of its own. They
are dedented at import, so the budget measures the same text on every Python.

**The evidence distinction, kept.** A catalogue description is a finding aid,
never the record. Tools say so; a contract test enforces it.

**A citation core on every record.** Any result that names a record carries
its id, its reference, its holder and its Discovery page.

**A structured result, never an exception.** Every tool catches its failures
and returns an `error` envelope. Sweep tests call every tool with Discovery
failing, and answering in the wrong shape, and fail if one raises.

**TNA's terms, kept.** No cache of anything the API returns, no setting that
quickens the pace past one request a second or raises the budget past 3,000 a
day, and every request counted. See [docs/DESIGN.md](docs/DESIGN.md#terms-that-shape-the-code).

**Nothing that writes to a site, and nothing that works around a bot check.**

**Nothing that widens what an argument can reach.** Treat every argument as
written by someone else's text. A new argument is narrowed before it reaches
a request, and comes with a test in `tests/test_security.py`.

**A new fixture recorded, not invented,** when a change depends on how the API
answers, with what was observed and when added to `docs/API-NOTES.md`. Keep
fixtures to historical records.

**The snapshot, when the surface changes.** Renaming or adding a tool or a
parameter fails the snapshot test on purpose. Regenerate it with
`uv run python -m tests.regen_tool_snapshot`, update the README table, and add
a `CHANGELOG.md` entry.

## Releasing

A maintainer bumps `__version__` in `src/tna_discovery_mcp/__init__.py` and
both versions in `server.json`, moves the changelog's Unreleased entries under
the new version, and publishes a GitHub release tagged `v<version>`. The
release workflow builds the tag, publishes to PyPI by Trusted Publishing, and
lists the version in the MCP Registry.
