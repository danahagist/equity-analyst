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
    "rank",
    "qualify",
    "levels",
    "etf-exposure",
    "etf-strategy",
    "digest",
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
    p_submit.add_argument("--file", help="Path to the verdict JSON (default: read from stdin)")
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
        help="Fetch a named universe (Russell 1000 via the Wikipedia components table)",
    )
    p_screen.add_argument("--tickers-file", help="File with one ticker per line")
    p_screen.add_argument("--top", type=int, default=25, help="Rows to show (default: 25)")
    p_screen.add_argument("--limit", type=int, help="Screen only the first N tickers (for testing)")
    p_screen.add_argument(
        "--delay", type=float, default=0.3, help="Seconds between fetches (default: 0.3)"
    )
    p_screen.add_argument(
        "--no-db", action="store_true", help="Do not record the ranking in SQLite"
    )
    p_screen.add_argument("--quiet", action="store_true", help="Suppress progress messages")

    p_rank = sub.add_parser(
        "rank",
        help="Order the committee walk-down queue: blended score + skill-gated forecast veto",
    )
    p_rank.add_argument(
        "tickers", nargs="*", metavar="ticker", help="Candidates (or use --screen-csv)"
    )
    p_rank.add_argument("--screen-csv", help="Take the top rows of a `screen` CSV")
    p_rank.add_argument(
        "--top", type=int, default=10, help="Rows to take from the CSV (default: 10)"
    )
    p_rank.add_argument("--as-of", help="Packet date (defaults to the latest per ticker)")

    p_qualify = sub.add_parser(
        "qualify",
        help="Walk-down bar check: PM Buy+, medium+ conviction, committee not split",
    )
    p_qualify.add_argument(
        "tickers", nargs="+", metavar="ticker", help="Ticker(s) with finalized sessions"
    )
    p_qualify.add_argument(
        "--need", type=int, default=5, help="Qualifying names the walk-down needs (default: 5)"
    )
    p_qualify.add_argument("--as-of", help="Session date (defaults to the latest packet)")

    p_levels = sub.add_parser(
        "levels",
        help="Phase 4: forecast-interval entry/exit levels (decision support, no orders)",
    )
    p_levels.add_argument(
        "tickers", nargs="+", metavar="ticker", help="Ticker(s) with a prepared packet"
    )
    p_levels.add_argument("--as-of", help="Session date (defaults to the latest packet)")

    p_etf = sub.add_parser(
        "etf-exposure",
        help="Phase 6: rank ETFs by exposure to your candidate stocks (broader exposure)",
    )
    p_etf.add_argument("tickers", nargs="+", metavar="ticker", help="Candidate stock ticker(s)")
    p_etf.add_argument(
        "--etfs", help="Comma-separated ETF universe to sweep (default: curated list)"
    )
    p_etf.add_argument("--top", type=int, default=20, help="Rows to show (default: 20)")
    p_etf.add_argument(
        "--delay", type=float, default=0.3, help="Seconds between fetches (default: 0.3)"
    )
    p_etf.add_argument("--quiet", action="store_true", help="Suppress progress messages")

    p_strategy = sub.add_parser(
        "etf-strategy",
        help="Coverage-optimized ETF basket over the screen's top names, with risk/return stats",
    )
    p_strategy.add_argument(
        "tickers", nargs="*", metavar="ticker", help="Candidates (or use --screen-csv)"
    )
    p_strategy.add_argument("--screen-csv", help="Take the top rows of a `screen` CSV")
    p_strategy.add_argument(
        "--top", type=int, default=50, help="Rows to take from the CSV (default: 50)"
    )
    p_strategy.add_argument(
        "--max-etfs", type=int, default=5, help="Maximum funds in the basket (default: 5)"
    )
    p_strategy.add_argument(
        "--etfs", help="Comma-separated ETF universe to sweep (default: curated list)"
    )
    p_strategy.add_argument(
        "--period", default="5y", help="Price history for the statistics (default: 5y)"
    )
    p_strategy.add_argument(
        "--no-save", action="store_true", help="Do not write the report to outputs/"
    )
    p_strategy.add_argument(
        "--delay", type=float, default=0.3, help="Seconds between fetches (default: 0.3)"
    )
    p_strategy.add_argument("--quiet", action="store_true", help="Suppress progress messages")

    p_digest = sub.add_parser(
        "digest",
        help="Combined decision digest: all analysts + consensus + levels + ETFs + exec summary",
    )
    p_digest.add_argument(
        "tickers", nargs="+", metavar="ticker", help="Shortlist ticker(s) with finalized sessions"
    )
    p_digest.add_argument("--as-of", help="Session date (defaults to the latest packet)")
    p_digest.add_argument(
        "--exec-summary-file", help="Markdown file with the LLM-authored executive summary"
    )
    p_digest.add_argument(
        "--no-etf", action="store_true", help="Skip the ETF-exposure section (no fetches)"
    )
    p_digest.add_argument(
        "--etf-strategy-file",
        help="Embed a saved `etf-strategy` report as the ETF section (skips the sweep)",
    )
    p_digest.add_argument(
        "--no-save", action="store_true", help="Do not write the digest to outputs/"
    )
    p_digest.add_argument(
        "--delay", type=float, default=0.3, help="Seconds between ETF fetches (default: 0.3)"
    )
    p_digest.add_argument("--quiet", action="store_true", help="Suppress progress messages")

    p_notify = sub.add_parser(
        "notify", help="Email a report (stdlib SMTP; configure SMTP_* in .env)"
    )
    p_notify.add_argument("--subject", required=True, help="Email subject")
    p_notify.add_argument("--body-file", help="Path to a text/markdown body (else a stub)")
    p_notify.add_argument(
        "--attach", action="append", default=[], metavar="PATH", help="File to attach (repeatable)"
    )

    p_compare = sub.add_parser("compare", help="Rank the latest stored run per ticker side by side")
    p_compare.add_argument(
        "tickers", nargs="*", help="Tickers to compare (default: every stored ticker)"
    )

    p_skill = sub.add_parser("skill-report", help="Audit stored forecasts against realized prices")
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
        "rank": _cmd_rank,
        "qualify": _cmd_qualify,
        "levels": _cmd_levels,
        "etf-exposure": _cmd_etf_exposure,
        "etf-strategy": _cmd_etf_strategy,
        "digest": _cmd_digest,
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
        build_screen_report(ranked, top=args.top, excluded=excluded, failures=failures, as_of=as_of)
    )
    if ranked:
        # SQLite is the system of record (rank/etf-strategy read it back, and
        # the funnel stays joinable against forecasts and committee runs);
        # the CSV is the export layer.
        if not args.no_db:
            from equity_analyst.storage import connect, save_screen_results

            conn = connect(settings.db_path)
            try:
                save_screen_results(conn, as_of=as_of, ranked=ranked)
            finally:
                conn.close()
            print(f"\n[{len(ranked)} ranked names recorded in {settings.db_path}]")
        csv_path = write_screen_csv(ranked, settings.outputs_dir / f"screen-{as_of}.csv")
        print(f"[full ranking exported to {csv_path}]")
    return 0


def _cmd_rank(args: argparse.Namespace) -> int:
    from datetime import date
    from equity_analyst.config import get_settings
    from equity_analyst.rank import build_queue, build_rank_report
    from equity_analyst.session import load_packet

    candidates = _screen_candidates(args)
    if isinstance(candidates, int):
        return candidates

    settings = get_settings()
    packets: dict[str, dict] = {}
    for ticker, _ in candidates:
        try:
            packets[ticker] = load_packet(settings.runs_dir, ticker, args.as_of)
        except (FileNotFoundError, ValueError):
            pass  # flagged as "no packet" in the queue, not dropped
    queue = build_queue(candidates, packets)
    print(build_rank_report(queue, as_of=date.today().isoformat()))
    return 0


def _screen_candidates(args: argparse.Namespace) -> list[tuple[str, float | None]] | int:
    """Resolve (ticker, blended) candidates for `rank` / `etf-strategy`.

    Priority: --screen-csv if given, else the latest screen stored in SQLite
    (the system of record — a plain `equity-analyst rank --top 50` works right
    after `screen` with no file paths involved). Explicit tickers keep their
    position at the front but inherit their blended score from the screen when
    present (an unscored 'extra' name must not silently out-weigh every
    genuinely screened one). Returns an exit code on failure.
    """
    from pathlib import Path

    from equity_analyst.rank import read_screen_csv

    candidates: list[tuple[str, float | None]] = [(t.upper(), None) for t in args.tickers]
    screen_rows: list[tuple[str, float | None]] = []
    if args.screen_csv:
        try:
            screen_rows = read_screen_csv(Path(args.screen_csv), top=args.top)
        except (OSError, ValueError, KeyError) as exc:
            print(f"error: cannot read screen CSV {args.screen_csv} — {exc}")
            return 1
    else:
        from equity_analyst.config import get_settings
        from equity_analyst.storage import connect, load_screen_results

        conn = connect(get_settings().db_path)
        try:
            screen_date, screen_rows = load_screen_results(conn, top=args.top)
        finally:
            conn.close()
        if screen_rows:
            print(f"[using the stored {screen_date} screen, top {len(screen_rows)}]")

    if screen_rows:
        blended_by_ticker = dict(screen_rows)
        explicit = {t for t, _ in candidates}
        candidates = [(t, blended_by_ticker.get(t)) for t, _ in candidates]
        candidates += [(t, b) for t, b in screen_rows if t not in explicit]
    if not candidates:
        print(
            "error: no candidates — run `equity-analyst screen` first (its ranking "
            "is stored in SQLite), or pass tickers / --screen-csv"
        )
        return 2
    return candidates


def _etf_universe(args: argparse.Namespace) -> list[str]:
    from equity_analyst.etf_exposure import DEFAULT_ETF_UNIVERSE

    if getattr(args, "etfs", None):
        return [e.strip().upper() for e in args.etfs.split(",") if e.strip()]
    return list(dict.fromkeys(DEFAULT_ETF_UNIVERSE))


def _cmd_qualify(args: argparse.Namespace) -> int:
    from equity_analyst.committee.consensus import compute_consensus
    from equity_analyst.config import get_settings
    from equity_analyst.digest import Qualification, build_qualify_report, check_bar
    from equity_analyst.session import load_packet, load_session_verdicts

    settings = get_settings()
    quals = []
    worst = 0
    for ticker in args.tickers:
        try:
            packet = load_packet(settings.runs_dir, ticker, args.as_of)
            verdicts, pm, _failures = load_session_verdicts(packet)
            quals.append(check_bar(packet["ticker"], pm, compute_consensus(verdicts)))
        except (FileNotFoundError, ValueError) as exc:
            # A ticker that fails to load is a visible ✗ row with the reason and
            # a non-zero exit — not a silent absence the operator misreads as
            # "not yet committee'd".
            quals.append(
                Qualification(
                    ticker=ticker.upper(),
                    qualifies=False,
                    reasons=[f"session could not be loaded: {exc}"],
                )
            )
            worst = 1
    if not quals:
        return 1
    print(build_qualify_report(quals, need=args.need))
    return worst


def _cmd_etf_strategy(args: argparse.Namespace) -> int:
    from datetime import date

    from equity_analyst.config import get_settings
    from equity_analyst.data.yahoo import YahooDataSource
    from equity_analyst.etf_exposure import fetch_holdings, fetch_profiles
    from equity_analyst.etf_strategy import (
        basket_correlations,
        build_basket,
        build_strategy_report,
        fetch_stats,
    )

    candidates = _screen_candidates(args)
    if isinstance(candidates, int):
        return candidates

    settings = get_settings()
    settings.ensure_dirs()
    data_source = YahooDataSource()
    holdings, failures = fetch_holdings(
        _etf_universe(args), data_source=data_source, delay=args.delay, progress=_progress(args)
    )
    picks, uncovered = build_basket(candidates, holdings, max_etfs=args.max_etfs)
    if not picks:
        print("error: no swept fund holds any of the screened names in its top holdings")
        return 1
    stats = fetch_stats(
        [p.etf for p in picks],
        data_source=data_source,
        period=args.period,
        delay=args.delay,
        progress=_progress(args),
    )
    descriptions = fetch_profiles(
        [p.etf for p in picks],
        data_source=data_source,
        delay=args.delay,
        progress=_progress(args),
    )
    as_of = date.today().isoformat()
    report = build_strategy_report(
        picks,
        stats,
        candidates=candidates,
        uncovered=uncovered,
        correlations=basket_correlations(stats),
        swept=len(holdings) + len(failures),
        as_of=as_of,
        descriptions=descriptions,
    )
    print(report)
    if not args.no_save:
        out_path = settings.outputs_dir / f"etf-strategy-{as_of}.md"
        out_path.write_text(report, encoding="utf-8")
        print(f"\n[saved to {out_path}]")
    return 0


def _cmd_digest(args: argparse.Namespace) -> int:
    from datetime import date
    from pathlib import Path

    from equity_analyst.config import get_settings
    from equity_analyst.digest import build_digest
    from equity_analyst.session import load_packet, load_session_verdicts

    settings = get_settings()
    settings.ensure_dirs()

    entries = []
    excluded: list[tuple[str, str]] = []
    for ticker in args.tickers:
        try:
            packet = load_packet(settings.runs_dir, ticker, args.as_of)
            verdicts, pm, _failures = load_session_verdicts(packet)
        except (FileNotFoundError, ValueError) as exc:
            # Disclosed inside the digest itself, not just on stdout — the
            # saved/emailed document must never silently present itself as
            # complete while missing a qualifier.
            print(f"error: {exc}")
            excluded.append((ticker.upper(), str(exc)))
            continue
        entries.append({"packet": packet, "verdicts": verdicts, "pm": pm})
    if not entries:
        return 1

    exec_summary = None
    if args.exec_summary_file:
        try:
            exec_summary = Path(args.exec_summary_file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot read {args.exec_summary_file} — {exc}")
            return 1

    etf_section = None
    if args.etf_strategy_file:
        try:
            etf_section = Path(args.etf_strategy_file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot read {args.etf_strategy_file} — {exc}")
            return 1
    elif not args.no_etf:
        from equity_analyst.data.yahoo import YahooDataSource
        from equity_analyst.etf_exposure import (
            build_exposure,
            build_exposure_report,
            fetch_holdings,
            fetch_profiles,
        )

        tickers = [e["packet"]["ticker"] for e in entries]
        data_source = YahooDataSource()
        universe = _etf_universe(args)
        holdings, failures = fetch_holdings(
            universe, data_source=data_source, delay=args.delay, progress=_progress(args)
        )
        exposures = build_exposure(tickers, holdings)
        etf_section = build_exposure_report(
            exposures,
            tickers=tickers,
            top=10,
            failures=failures,
            as_of=date.today().isoformat(),
            swept=len(holdings) + len(failures),
            descriptions=fetch_profiles(
                [e.etf for e in exposures[:10]],
                data_source=data_source,
                delay=args.delay,
                progress=_progress(args),
            ),
        )

    as_of = date.today().isoformat()
    digest_md = build_digest(
        entries,
        as_of=as_of,
        exec_summary=exec_summary,
        etf_section=etf_section,
        excluded=excluded,
    )
    print(digest_md)
    if not args.no_save:
        out_path = settings.outputs_dir / f"digest-{as_of}.md"
        out_path.write_text(digest_md, encoding="utf-8")
        print(f"\n[saved to {out_path}]")
    return 1 if excluded else 0


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


def _cmd_etf_exposure(args: argparse.Namespace) -> int:
    from datetime import date

    from equity_analyst.data.yahoo import YahooDataSource
    from equity_analyst.etf_exposure import build_exposure, build_exposure_report, fetch_holdings

    holdings, failures = fetch_holdings(
        _etf_universe(args),
        data_source=YahooDataSource(),
        delay=args.delay,
        progress=_progress(args),
    )
    exposures = build_exposure(args.tickers, holdings)
    print(
        build_exposure_report(
            exposures,
            tickers=args.tickers,
            top=args.top,
            failures=failures,
            as_of=date.today().isoformat(),
            swept=len(holdings) + len(failures),
        )
    )
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
        send_email(settings.smtp, subject=args.subject, body=body, attachments=attachments)
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
