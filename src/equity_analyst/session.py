"""Claude-Code-native committee sessions (the keyless mode).

Instead of the tool calling the Anthropic API, Claude Code performs the LLM
seats in-chat. Python keeps everything deterministic, and the flow is staged:

  1. ``prep``      — fetch data, run the forecast engine, compute the Technical
                     verdict, and write a *packet*: seat briefings (the same
                     prompt library the API mode uses) + a JSON state file.
  2. (in chat)     — Claude Code runs each LLM seat (ideally as independent
                     subagents) and writes their verdicts to a JSON file.
  3. ``consensus`` — deterministic agreement summary + the PM briefing.
  4. (in chat)     — Claude Code writes the PM synthesis into the same file.
  5. ``finalize``  — validate, render the report, persist run + forecasts.

The packet/verdict files live under ``data/runs/`` (gitignored). The same
verdict schema and report builder serve both modes, so reports and the SQLite
record are identical regardless of who did the LLM work.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from equity_analyst.committee.consensus import compute_consensus
from equity_analyst.committee.fundamental import FundamentalAnalyst
from equity_analyst.committee.news_social import NewsSocialAnalyst
from equity_analyst.committee.portfolio_manager import (
    PM_SCHEMA,
    PM_SYSTEM,
    PMSynthesis,
    build_pm_prompt,
    pm_from_parsed,
)
from equity_analyst.committee.research import ResearchAnalyst
from equity_analyst.committee.technical import TechnicalAnalyst
from equity_analyst.committee.verdict import VERDICT_SCHEMA, Verdict
from equity_analyst.data.base import MarketDataSource
from equity_analyst.forecast.engine import ForecastEngine
from equity_analyst.pipeline import RunResult, _mechanical_pm, gather_market_data
from equity_analyst.report import build_report
from equity_analyst.storage import save_forecast_rows, save_run, upsert_prices

# The LLM seats Claude Code performs, in briefing order.
LLM_SEATS = ("Fundamental", "News/Social", "Research")

_SEAT_BUILDERS = {
    "Fundamental": (FundamentalAnalyst, False),
    "News/Social": (NewsSocialAnalyst, True),
    "Research": (ResearchAnalyst, True),
}


@dataclass
class PrepResult:
    ticker: str
    as_of: str
    packet_path: Path
    verdicts_path: Path
    markdown: str


def prep_packet(
    ticker: str,
    *,
    data_source: MarketDataSource,
    runs_dir: Path,
    engine: ForecastEngine | None = None,
    period: str = "5y",
    conn: sqlite3.Connection | None = None,
    progress=None,
) -> PrepResult:
    """Stage 1: gather data, run the forecast, emit briefings + state."""
    ticker = ticker.upper()
    snapshot = gather_market_data(
        ticker, data_source=data_source, engine=engine, period=period, progress=progress
    )
    context, forecast = snapshot.context, snapshot.forecast
    as_of = snapshot.as_of

    technical = TechnicalAnalyst().evaluate(context)

    briefings = {}
    for seat, (cls, needs_search) in _SEAT_BUILDERS.items():
        system, prompt = cls(llm=None).build_prompt(context)
        briefings[seat] = {"system": system, "prompt": prompt, "web_search": needs_search}

    if conn is not None:
        upsert_prices(conn, ticker, snapshot.prices)
        save_forecast_rows(
            conn,
            ticker,
            as_of,
            [
                {
                    "label": h.label,
                    "target_date": h.target_date,
                    "model": h.model,
                    "point": h.point,
                    "lower": h.lower,
                    "upper": h.upper,
                    "interval_level": h.interval_level,
                    "beats_baseline": h.beats_baseline,
                    "n_windows": h.n_backtest_windows,
                }
                for h in forecast.horizons
            ],
        )

    runs_dir.mkdir(parents=True, exist_ok=True)
    packet_path = runs_dir / f"{ticker}-{as_of}-packet.json"
    verdicts_path = runs_dir / f"{ticker}-{as_of}-verdicts.json"
    packet = {
        "ticker": ticker,
        "as_of": as_of,
        "last_price": context.last_price,
        "technical_verdict": asdict(technical),
        "briefings": briefings,
        "fundamentals": context.fundamentals,
        "analyst_info": context.analyst_info,
        "verdicts_path": str(verdicts_path),
    }
    packet_path.write_text(json.dumps(packet, indent=2))

    markdown = _packet_markdown(packet, technical)
    return PrepResult(
        ticker=ticker,
        as_of=as_of,
        packet_path=packet_path,
        verdicts_path=verdicts_path,
        markdown=markdown,
    )


def load_packet(runs_dir: Path, ticker: str, as_of: str | None = None) -> dict:
    """Load a packet by ticker (+ optional as-of); latest as-of wins otherwise."""
    ticker = ticker.upper()
    if as_of:
        path = runs_dir / f"{ticker}-{as_of}-packet.json"
        if not path.exists():
            raise FileNotFoundError(f"no packet at {path} — run `equity-analyst prep {ticker}`")
        return json.loads(path.read_text())
    candidates = sorted(runs_dir.glob(f"{ticker}-*-packet.json"))
    if not candidates:
        raise FileNotFoundError(
            f"no packet for {ticker} in {runs_dir} — run `equity-analyst prep {ticker}`"
        )
    return json.loads(candidates[-1].read_text())


def load_session_verdicts(
    packet: dict,
) -> tuple[list[Verdict], PMSynthesis | None, list[tuple[str, str]]]:
    """Read the session verdicts file and validate it against the schema.

    Returns (all verdicts including Technical, pm-or-None, failures). Missing
    seats are failures, not fatal — mirroring the API pipeline's isolation.
    """
    technical = Verdict(**packet["technical_verdict"])
    verdicts: list[Verdict] = [technical]
    failures: list[tuple[str, str]] = []

    path = Path(packet["verdicts_path"])
    session: dict = {}
    if path.exists():
        try:
            session = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"verdicts file {path} is not valid JSON: {exc}") from exc

    provided = {v.get("analyst"): v for v in session.get("verdicts", [])}
    unknown = set(provided) - set(LLM_SEATS)
    if unknown:
        raise ValueError(
            f"unknown analyst name(s) {sorted(unknown)} in {path}; expected {list(LLM_SEATS)}"
        )
    for seat in LLM_SEATS:
        raw = provided.get(seat)
        if raw is None:
            failures.append((seat, "no verdict provided in session"))
            continue
        try:
            verdicts.append(
                Verdict(
                    analyst=seat,
                    rating=int(raw["rating"]),
                    conviction=str(raw["conviction"]),
                    horizon=str(raw["horizon"]),
                    evidence=str(raw["evidence"]),
                    writeup=str(raw.get("writeup", "")),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"invalid verdict for {seat} in {path}: {exc}") from exc

    pm: PMSynthesis | None = None
    if "pm" in session:
        try:
            pm = pm_from_parsed(session["pm"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"invalid 'pm' entry in {path}: {exc}") from exc

    return verdicts, pm, failures


def consensus_briefing(packet: dict) -> str:
    """Stage 3: deterministic consensus + the PM briefing for the chat."""
    verdicts, _pm, failures = load_session_verdicts(packet)
    if len(verdicts) < 2:
        raise ValueError(
            "need at least the Technical verdict plus one seat verdict before "
            f"consensus; still missing: {[name for name, _ in failures]}"
        )
    consensus = compute_consensus(verdicts)
    ticker = packet["ticker"]
    lines = [
        f"MECHANICAL CONSENSUS for {ticker} (deterministic):",
        f"  {consensus.headline}",
        f"  Vote split: {consensus.counts} | blended score {consensus.blended_score:+.2f} "
        f"| agreement: {consensus.agreement_level}",
    ]
    if failures:
        lines.append(f"  Seats missing (will be disclosed): {[n for n, _ in failures]}")
    lines += [
        "",
        "=" * 70,
        "PORTFOLIO MANAGER BRIEFING — perform this role now.",
        "",
        "SYSTEM:",
        PM_SYSTEM,
        "",
        "TASK:",
        build_pm_prompt(ticker, verdicts, consensus),
        "",
        "=" * 70,
        "Return the synthesis as JSON with exactly these keys "
        "(schema: rating int −2…+2; conviction low|medium|high; horizon str; "
        "synthesis str; key_risks [str]; horizon_fit [str] — one line each for 1w/1m/1y):",
        json.dumps({k: v for k, v in PM_SCHEMA["properties"].items()}, indent=2),
        "",
        f"Add it under the top-level key \"pm\" in {packet['verdicts_path']}, then run:",
        f"  equity-analyst finalize {ticker}",
    ]
    return "\n".join(lines)


def finalize_run(
    packet: dict,
    *,
    output_dir: Path | None = None,
    conn: sqlite3.Connection | None = None,
    now: str | None = None,
) -> RunResult:
    """Stage 5: validate the session, render + persist the report."""
    ticker, as_of = packet["ticker"], packet["as_of"]
    verdicts, pm, failures = load_session_verdicts(packet)
    consensus = compute_consensus(verdicts)

    if pm is None:
        failures.append(
            ("Portfolio Manager", "no synthesis provided; mechanical consensus reported")
        )
        pm = _mechanical_pm(consensus)

    report_md = build_report(
        ticker=ticker,
        as_of=as_of,
        verdicts=verdicts,
        consensus=consensus,
        pm=pm,
        last_price=packet.get("last_price"),
        failures=failures,
    )

    output_path = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{ticker}-{as_of}.md"
        output_path.write_text(report_md)

    if conn is not None:
        created_at = now or datetime.now(timezone.utc).isoformat()
        save_run(
            conn,
            ticker=ticker,
            as_of=as_of,
            created_at=created_at,
            pm_rating=pm.rating,
            pm_conviction=pm.conviction,
            consensus_leaning=consensus.leaning,
            blended_score=consensus.blended_score,
            report_md=report_md,
        )

    return RunResult(
        ticker=ticker,
        as_of=as_of,
        report_md=report_md,
        consensus=consensus,
        pm=pm,
        verdicts=verdicts,
        failures=failures,
        output_path=output_path,
    )


def _packet_markdown(packet: dict, technical: Verdict) -> str:
    """Human/Claude-readable packet: technical verdict + seat briefings."""
    ticker, as_of = packet["ticker"], packet["as_of"]
    price = (
        f"Last price: ${packet['last_price']:,.2f}"
        if packet.get("last_price") is not None
        else ""
    )
    out = [
        f"# Committee packet — {ticker} ({as_of})",
        price,
        "",
        "## Technical analyst (deterministic — verdict already recorded)",
        "",
        f"**{technical.rating_label}** (rating {technical.rating:+d}, "
        f"{technical.conviction} conviction, horizon {technical.horizon})",
        "",
        technical.evidence,
        "",
        "## Seat briefings — perform each independently",
        "",
    ]
    for seat, briefing in packet["briefings"].items():
        search = "REQUIRED — search the live web" if briefing["web_search"] else "not needed"
        out += [
            f"### {seat} (web search: {search})",
            "",
            "SYSTEM:",
            briefing["system"],
            "",
            "TASK:",
            briefing["prompt"],
            "",
        ]
    schema_props = json.dumps(VERDICT_SCHEMA["properties"], indent=2)
    out += [
        "## Verdict format",
        "",
        "Each seat produces a full written analysis (`writeup`) plus a verdict:",
        "```json",
        schema_props,
        "```",
        f"Write all seats to `{packet['verdicts_path']}` as:",
        '```json\n{"verdicts": [{"analyst": "Fundamental", "rating": 1, '
        '"conviction": "high", "horizon": "1y", "evidence": "…", "writeup": "…"}, …]}\n```',
        f"(valid analyst names: {list(LLM_SEATS)})",
        "",
        f"Then run: `equity-analyst consensus {ticker}`",
    ]
    return "\n".join(line for line in out if line is not None)
