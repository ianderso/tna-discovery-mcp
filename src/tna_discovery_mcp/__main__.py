"""Entry point: ``python -m tna_discovery_mcp`` / the ``tna-discovery-mcp`` script."""

from __future__ import annotations

from .server import run


def main() -> None:
    run()


if __name__ == "__main__":
    main()
