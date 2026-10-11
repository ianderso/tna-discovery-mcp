<!-- What this changes and why. Link the issue it closes, if there is one. -->

## Checklist

What each item means is in [CONTRIBUTING.md](https://github.com/ianderso/tna-discovery-mcp/blob/main/CONTRIBUTING.md#what-a-change-carries).

- [ ] A test that fails without this change.
- [ ] `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
- [ ] Tool descriptions are written for the model and fit under `DESCRIPTION_BUDGET`. Raising it takes a pull request of its own, saying why.
- [ ] Anything returning a catalogue description says it is a finding aid, not the record.
- [ ] Every result that names a record carries its id, reference, holder and Discovery page.
- [ ] Failures come back as an `error` result, not an exception.
- [ ] TNA's terms are kept: no cache of API content, no faster than one request a second, no more than 3,000 a day, every request counted.
- [ ] If a tool or parameter changed: `tests/fixtures/tool_schema.json` is regenerated and the README table is updated.
- [ ] If this relies on how the API answers: a recorded fixture, and what was observed and when in `docs/API-NOTES.md`.
- [ ] A `CHANGELOG.md` entry, if users will notice the change.
- [ ] Nothing here writes to a site or works around a bot check.
