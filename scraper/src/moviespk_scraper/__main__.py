"""Command-line entry point: ``python -m moviespk_scraper run --job ...`` (see ``cli.py``)."""

from __future__ import annotations

from moviespk_scraper.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
