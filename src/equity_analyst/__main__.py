"""Command-line entry point for equity-analyst."""

import argparse

from equity_analyst import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="equity-analyst",
        description="An equity research tool.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.parse_args(argv)

    # Features to come.
    print("equity-analyst — scaffold. No commands wired up yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
