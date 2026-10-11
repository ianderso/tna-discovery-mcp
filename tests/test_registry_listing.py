"""Tests over the MCP Registry listing: ``server.json`` and the README marker.

The registry lists what ``server.json`` says, and confirms that the PyPI
package is this project's by finding ``mcp-name: <name>`` in the README that
PyPI holds for that exact version. Nothing else fails if the three drift
apart; the release would, after PyPI had already accepted it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tna_discovery_mcp import __version__

ROOT = Path(__file__).parent.parent
SERVER_JSON = json.loads((ROOT / "server.json").read_text())
PACKAGE = SERVER_JSON["packages"][0]


def test_server_json_carries_the_package_version_twice():
    assert SERVER_JSON["version"] == __version__
    assert PACKAGE["version"] == __version__


def test_server_json_points_at_this_package_on_pypi():
    assert SERVER_JSON["name"] == "io.github.ianderso/tna-discovery-mcp"
    assert PACKAGE["registryType"] == "pypi"
    assert PACKAGE["identifier"] == "tna-discovery-mcp"


def test_the_readme_carries_the_registry_marker_for_this_name():
    marker = re.escape(f"mcp-name: {SERVER_JSON['name']}")
    assert re.search(marker + r"(\s|-->|<)", (ROOT / "README.md").read_text())


def test_server_json_declares_every_setting_the_server_reads():
    read = set(
        re.findall(
            r'"(TNA_DISCOVERY_[A-Z_]+)"', (ROOT / "src/tna_discovery_mcp/config.py").read_text()
        )
    )
    declared = {v["name"] for v in PACKAGE["environmentVariables"]}
    assert declared == read


def test_no_setting_is_required_or_secret():
    """The server needs no key; a client should not ask for one."""
    for var in PACKAGE["environmentVariables"]:
        assert not var.get("isRequired"), var["name"]
        assert not var.get("isSecret"), var["name"]


def test_the_description_fits_the_registry_limit():
    """The MCP Registry refuses a description over 100 characters, after PyPI has the release."""
    assert len(SERVER_JSON["description"]) <= 100


def test_the_readme_passes_on_tnas_requests_and_the_no_cache_rule():
    """What TNA's terms ask of developers is said where users will read it."""
    readme = " ".join((ROOT / "README.md").read_text().split())
    assert "webmaster@nationalarchives.gov.uk" in readme
    assert "IP address" in readme
    assert "no cache" in readme.lower() or "not cache" in readme.lower()
    assert "Open Government Licence" in readme
    assert "3,000" in readme
