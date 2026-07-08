"""Command-line entry point for equity-analyst."""

from __future__ import annotations

import argparse

from equity_analyst import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="equity-analyst",
        description="Investment-committee equity research for a stock ticker.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("ticker", nargs="?", help="Stock ticker, e.g. AAPL")
    parser.add_argument("--period", default="5y", help="Price history to pull (default: 5y)")
    parser.add_argument(
        "--no-save", action="store_true", help="Do not write the markdown report to outputs/"
    )
    parser.add_argument("--no-db", action="store_true", help="Do not persist the run to SQLite")
    args = parser.parse_args(argv)

    if not args.ticker:
        parser.print_help()
        return 0

    return _run(args)


def _run(args: argparse.Namespace) -> int:
    # Imports are local so `--version`/`--help` stay fast and dependency-light.
    from equity_analyst.config import get_settings
    from equity_analyst.data.yahoo import DataUnavailable, YahooDataSource
    from equity_analyst.llm.anthropic_client import AnthropicClient
    from equity_analyst.llm.base import LLMError
    from equity_analyst.pipeline import run_committee
    from equity_analyst.storage import connect

    settings = get_settings()
    if not settings.anthropic_api_key:
        print("error: ANTHROPIC_API_KEY is not set (put it in .env). See .env.example.")
        return 2

    settings.ensure_dirs()
    conn = None if args.no_db else connect(settings.db_path)
    output_dir = None if args.no_save else settings.outputs_dir

    try:
        result = run_committee(
            args.ticker,
            data_source=YahooDataSource(),
            llm=AnthropicClient(api_key=settings.anthropic_api_key),
            period=args.period,
            output_dir=output_dir,
            conn=conn,
        )
    except DataUnavailable as exc:
        print(f"error: market data unavailable — {exc}")
        return 1
    except LLMError as exc:
        print(f"error: LLM call failed — {exc}")
        return 1
    finally:
        if conn is not None:
            conn.close()

    print(result.report_md)
    if result.output_path is not None:
        print(f"\n[saved to {result.output_path}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
