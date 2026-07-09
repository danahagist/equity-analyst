"""Command-line entry point for equity-analyst.

Two ways to run a committee:

- **Claude-Code-native (default, no API key):** staged — ``prep`` gathers data
  and prints seat briefings, Claude Code performs the LLM seats in-chat,
  ``consensus`` prints the deterministic summary + PM briefing, ``finalize``
  renders and persists the report. See the `run-analysis` skill.
- **Full-auto (`analyze`, needs ANTHROPIC_API_KEY):** the tool makes the LLM
  calls itself. Same prompts, same report.
"""

from __future__ import annotations

import argparse
import sys

from equity_analyst import __version__

_COMMANDS = (
    "analyze",
    "prep",
    "consensus",
    "finalize",
    "submit-verdict",
    "screen",
    "levels",
    "notify",
    "compare",
    "skill-report",
    "export",
)


def _force_utf8_stdio() -> None:
    """Windows consoles default to cp1252, which cannot encode the report's
    Unicode (minus signs, arrows). Reconfigure stdout/stderr to UTF-8 so the
    CLI works without PYTHONIOENCODING gymnastics."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):  # e.g. detached/closed streams
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    # Backward compat: `equity-analyst AAPL` == `equity-analyst analyze AAPL`.
    if argv and argv[0] not in _COMMANDS and not argv[0].startswith("-"):
        argv = ["analyze", *argv]

    parser = argparse.ArgumentParser(
        prog="equity-analyst",
        description="Investment-committee equity research for a stock ticker.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_analyze = sub.add_parser(
        "analyze", help="Full-auto committee run (requires ANTHROPIC_API_KEY)"
    )
    p_prep = sub.add_parser(
        "prep", help="Stage 1 (keyless): fetch data, forecast, print seat briefings"
    )
    for p in (p_analyze, p_prep):
        p.add_argument("tickers", nargs="+", metavar="ticker", help="Stock ticker(s), e.g. AAPL")
        p.add_argument("--period", default="5y", help="Price history to pull (default: 5y)")
        p.add_argument("--no-db", action="store_true", help="Do not persist to SQLite")
        p.add_argument("--quiet", action="store_true", help="Suppress progress messages")
    p_analyze.add_argument(
        "--no-save", action="store_true", help="Do not write the markdown report to outputs/"
    )

    p_consensus = sub.add_parser(
        "consensus", help="Stage 3 (keyless): mechanical consensus + PM briefing"
    )
    p_finalize = sub.add_parser(
        "finalize", help="Stage 5 (keyless): validate session, render + persist report"
    )
    for p in (p_consensus, p_finalize):
        p.add_argument(
            "tickers", nargs="+", metavar="ticker", help="Ticker(s) of prepared session(s)"
        )
        p.add_argument("--as-of", help="Session date (defaults to the latest packet)")
    p_finalize.add_argument(
        "--no-save", action="store_true", help="Do not write the markdown report to outputs/"
    )
    p_finalize.add_argument("--no-db", action="store_true", help="Do not persist to SQLite")

    p_submit = sub.add_parser(
        "submit-verdict",
        help="Stages 2/4 (keyless): validate and record one seat's verdict JSON",
    )
    p_submit.add_argument("ticker", help="Ticker of the prepared session")
    p_submit.add_argument(
        "--analyst",
        required=True,
        choices=("Fundamental", "News/Social", "Research", "PM"),
        help="Which seat this verdict belongs to (PM = portfolio-manager synthesis)",
    )
    p_submit.add_argument(
        "--file", help="Path to the verdict JSON (default: read from stdin)"
    )
    p_submit.add_argument("--as-of", help="Session date (defaults to the latest packet)")

    p_screen = sub.add_parser(
        "screen",
        help="Deterministic pre-committee screen (blended Street-gap + GARP), no LLM",
    )
    p_screen.add_argument(
        "tickers", nargs="*", metavar="ticker", help="Universe to screen (or use --universe)"
    )
    p_screen.add_argument(
        "--universe",
        choices=("russell1000",),
        help="Fetch a named universe (Russell 1000 via iShares IWB holdings)",
    )
    p_screen.add_argument("--tickers-file", help="File with one ticker per line")
    p_screen.add_argument("--top", type=int, default=25, help="Rows to show (default: 25)")
    p_screen.add_argument(
        "--limit", type=int, help="Screen only the first N tickers (for testing)"
    )
    p_screen.add_argument(
        "--delay", type=float, default=0.3, help="Seconds between fetches (default: 0.3)"
    )
    p_screen.add_argument("--quiet", action="store_true", help="Suppress progress messages")

    p_levels = sub.add_parser(
        "levels",
        help="Phase 4: forecast-interval entry/exit levels (decision support, no orders)",
    )
    p_levels.add_argument(
        "tickers", nargs="+", metavar="ticker", help="Ticker(s) with a prepared packet"
    )
    p_levels.add_argument("--as-of", help="Session date (defaults to the latest packet)")

    p_notify = sub.add_parser(
        "notify", help="Email a report (stdlib SMTP; configure SMTP_* in .env)"
    )
    p_notify.add_argument("--subject", required=True, help="Email subject")
    p_notify.add_argument("--body-file", help="Path to a text/markdown body (else a stub)")
    p_notify.add_argument(
        "--attach", action="append", default=[], metavar="PATH", help="File to attach (repeatable)"
    )

    p_compare = sub.add_parser(
        "compare", help="Rank the latest stored run per ticker side by side"
    )
    p_compare.add_argument(
        "tickers", nargs="*", help="Tickers to compare (default: every stored ticker)"
    )

    p_skill = sub.add_parser(
        "skill-report", help="Audit stored forecasts against realized prices"
    )
    p_skill.add_argument("--ticker", help="Restrict the audit to one ticker")

    p_export = sub.add_parser("export", help="Export the SQLite record to CSV or Excel")
    p_export.add_argument(
        "--format", choices=("csv", "xlsx"), default="csv", help="Export format (default: csv)"
    )
    p_export.add_argument("--out", help="Output directory (default: outputs/export)")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return {
        "analyze": _cmd_analyze,
        "prep": _cmd_prep,
        "consensus": _cmd_consensus,
        "finalize": _cmd_finalize,
        "submit-verdict": _cmd_submit_verdict,
        "screen": _cmd_screen,
        "levels": _cmd_levels,
        "notify": _cmd_notify,
        "compare": _cmd_compare,
        "skill-report": _cmd_skill_report,
        "export": _cmd_export,
    }[args.command](args)


def _for_each_ticker(args: argparse.Namespace, run_one) -> int:
    """Run a per-ticker command over every requested ticker.

    One ticker failing does not stop the rest (mirrors the committee's
    failure-isolation principle); the exit code is the worst one seen.
    """
    worst = 0
    for i, ticker in enumerate(args.tickers):
        if i:
            print("\n" + "=" * 70 + "\n")
        worst = max(worst, run_one(ticker))
    return worst


def _progress(args: argparse.Namespace):
    if getattr(args, "quiet", False):
        return None
    return lambda msg: print(f"  {msg}", file=sys.stderr)


def _cmd_analyze(args: argparse.Namespace) -> int:
    from equity_analyst.config import get_settings
    from equity_analyst.data.yahoo import DataUnavailable, YahooDataSource
    from equity_analyst.llm.anthropic_client import AnthropicClient
    from equity_analyst.llm.base import LLMError
    from equity_analyst.pipeline import run_committee
    from equity_analyst.storage import connect

    settings = get_settings()
    if not settings.anthropic_api_key:
        print(
            "error: `analyze` (full-auto mode) needs ANTHROPIC_API_KEY in .env.\n"
            "No key? Use the keyless flow instead: `equity-analyst prep TICKER` "
            "and let Claude Code run the committee (see the run-analysis skill)."
        )
        return 2

    settings.ensure_dirs()
    output_dir = None if args.no_save else settings.outputs_dir

    def run_one(ticker: str) -> int:
        conn = None if args.no_db else connect(settings.db_path)
        try:
            result = run_committee(
                ticker,
                data_source=YahooDataSource(),
                llm=AnthropicClient(api_key=settings.anthropic_api_key),
                period=args.period,
                output_dir=output_dir,
                conn=conn,
                progress=_progress(args),
            )
        except DataUnavailable as exc:
            print(f"error: market data unavailable for {ticker} — {exc}")
            return 1
        except LLMError as exc:
            print(f"error: LLM call failed for {ticker} — {exc}")
            return 1
        finally:
            if conn is not None:
                conn.close()
        print(result.report_md)
        if result.output_path is not None:
            print(f"\n[saved to {result.output_path}]")
        return 0

    return _for_each_ticker(args, run_one)


def _cmd_prep(args: argparse.Namespace) -> int:
    from equity_analyst.config import get_settings
    from equity_analyst.data.yahoo import DataUnavailable, YahooDataSource
    from equity_analyst.session import prep_packet
    from equity_analyst.storage import connect

    settings = get_settings()
    settings.ensure_dirs()

    def run_one(ticker: str) -> int:
        conn = None if args.no_db else connect(settings.db_path)
        try:
            result = prep_packet(
                ticker,
                data_source=YahooDataSource(),
                runs_dir=settings.runs_dir,
                period=args.period,
                conn=conn,
                progress=_progress(args),
            )
        except DataUnavailable as exc:
            print(f"error: market data unavailable for {ticker} — {exc}")
            return 1
        finally:
            if conn is not None:
                conn.close()
        print(result.markdown)
        print(f"\n[packet saved to {result.packet_path}]")
        return 0

    return _for_each_ticker(args, run_one)


def _cmd_consensus(args: argparse.Namespace) -> int:
    from equity_analyst.config import get_settings
    from equity_analyst.session import consensus_briefing, load_packet

    settings = get_settings()

    def run_one(ticker: str) -> int:
        try:
            packet = load_packet(settings.runs_dir, ticker, args.as_of)
            print(consensus_briefing(packet))
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        return 0

    return _for_each_ticker(args, run_one)


def _cmd_finalize(args: argparse.Namespace) -> int:
    from equity_analyst.config import get_settings
    from equity_analyst.session import finalize_run, load_packet
    from equity_analyst.storage import connect

    settings = get_settings()
    settings.ensure_dirs()

    def run_one(ticker: str) -> int:
        conn = None if args.no_db else connect(settings.db_path)
        try:
            packet = load_packet(settings.runs_dir, ticker, args.as_of)
            result = finalize_run(
                packet,
                output_dir=None if args.no_save else settings.outputs_dir,
                conn=conn,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        finally:
            if conn is not None:
                conn.close()
        print(result.report_md)
        if result.output_path is not None:
            print(f"\n[saved to {result.output_path}]")
        return 0

    return _for_each_ticker(args, run_one)


def _cmd_submit_verdict(args: argparse.Namespace) -> int:
    import json

    from equity_analyst.config import get_settings
    from equity_analyst.session import load_packet, submit_verdict

    if args.file:
        from pathlib import Path

        try:
            raw = Path(args.file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot read {args.file} — {exc}")
            return 1
    else:
        raw = sys.stdin.read()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: verdict payload is not valid JSON — {exc}")
        return 1

    settings = get_settings()
    try:
        packet = load_packet(settings.runs_dir, args.ticker, args.as_of)
        path = submit_verdict(packet, analyst=args.analyst, payload=payload)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        return 1
    print(f"recorded {args.analyst} verdict for {args.ticker.upper()} in {path}")
    return 0


def _cmd_screen(args: argparse.Namespace) -> int:
    from datetime import date

    from equity_analyst.config import get_settings
    from equity_analyst.data.yahoo import YahooDataSource
    from equity_analyst.screen import (
        build_screen_report,
        fetch_russell1000,
        run_screen,
        score_rows,
        write_screen_csv,
    )

    tickers = [t.upper() for t in args.tickers]
    if args.tickers_file:
        from pathlib import Path

        tickers += [
            line.strip().upper()
            for line in Path(args.tickers_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    if args.universe == "russell1000":
        try:
            tickers += fetch_russell1000()
        except (OSError, ValueError) as exc:
            print(f"error: could not fetch Russell 1000 constituents — {exc}")
            return 1
    tickers = list(dict.fromkeys(tickers))  # dedupe, preserve order
    if not tickers:
        print("error: no tickers — pass tickers, --tickers-file, or --universe russell1000")
        return 2
    if args.limit:
        tickers = tickers[: args.limit]

    settings = get_settings()
    settings.ensure_dirs()
    rows, failures = run_screen(
        tickers,
        data_source=YahooDataSource(),
        delay=args.delay,
        progress=_progress(args),
    )
    ranked, excluded = score_rows(rows)
    as_of = date.today().isoformat()
    print(
        build_screen_report(
            ranked, top=args.top, excluded=excluded, failures=failures, as_of=as_of
        )
    )
    if ranked:
        csv_path = write_screen_csv(ranked, settings.outputs_dir / f"screen-{as_of}.csv")
        print(f"\n[full ranking saved to {csv_path}]")
    return 0


def _cmd_levels(args: argparse.Namespace) -> int:
    from datetime import date

    from equity_analyst.config import get_settings
    from equity_analyst.levels import build_levels_report, plan_from_packet
    from equity_analyst.session import load_packet

    settings = get_settings()
    plans = []
    for ticker in args.tickers:
        try:
            packet = load_packet(settings.runs_dir, ticker, args.as_of)
            plans.append(plan_from_packet(packet))
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}")
    if not plans:
        return 1
    print(build_levels_report(plans, as_of=date.today().isoformat()))
    return 0


def _cmd_notify(args: argparse.Namespace) -> int:
    from pathlib import Path

    from equity_analyst.config import get_settings
    from equity_analyst.notify import EmailNotConfigured, send_email

    settings = get_settings()
    attachments = [Path(p) for p in args.attach]
    missing = [str(p) for p in attachments if not p.exists()]
    if missing:
        print(f"error: attachment(s) not found: {', '.join(missing)}")
        return 1
    body = (
        Path(args.body_file).read_text(encoding="utf-8")
        if args.body_file
        else "Equity-analyst run complete. See attached report(s)."
    )
    try:
        send_email(
            settings.smtp, subject=args.subject, body=body, attachments=attachments
        )
    except EmailNotConfigured as exc:
        print(f"error: {exc}")
        return 2
    except OSError as exc:
        print(f"error: email send failed — {exc}")
        return 1
    print(f"emailed '{args.subject}' to {', '.join(settings.smtp.recipients)}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    from equity_analyst.comparison import build_comparison, load_latest_runs
    from equity_analyst.config import get_settings
    from equity_analyst.storage import connect

    settings = get_settings()
    conn = connect(settings.db_path)
    try:
        rows = load_latest_runs(conn, args.tickers or None)
        print(build_comparison(rows, requested=args.tickers or None))
    finally:
        conn.close()
    return 0


def _cmd_skill_report(args: argparse.Namespace) -> int:
    from datetime import date

    from equity_analyst.config import get_settings
    from equity_analyst.skill_report import build_skill_report, resolve_forecasts
    from equity_analyst.storage import connect

    settings = get_settings()
    today = date.today().isoformat()
    conn = connect(settings.db_path)
    try:
        resolved, unresolvable = resolve_forecasts(conn, today=today, ticker=args.ticker)
        print(build_skill_report(resolved, unresolvable=unresolvable, today=today))
    finally:
        conn.close()
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from pathlib import Path

    from equity_analyst.config import get_settings
    from equity_analyst.storage import connect
    from equity_analyst.storage.export import export_tables

    settings = get_settings()
    out_dir = Path(args.out) if args.out else settings.outputs_dir / "export"
    conn = connect(settings.db_path)
    try:
        paths = export_tables(conn, out_dir, fmt=args.format)
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1
    finally:
        conn.close()
    for path in paths:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
