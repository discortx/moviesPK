"""Command-line entry point: ``python -m moviespk_scraper``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from moviespk_scraper import __version__

JOBS = ("full", "seats", "canary")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="moviespk_scraper",
        description="MoviesPK scraper: collects cinema showtimes into MongoDB.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("job", choices=JOBS, help="job to run")
    parser.add_argument("--cinema", help="run only this cinema id")
    parser.add_argument(
        "--rebuild-images",
        action="store_true",
        help="ignore the unchanged-poster shortcut (manual recovery only)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"job '{args.job}' is not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
