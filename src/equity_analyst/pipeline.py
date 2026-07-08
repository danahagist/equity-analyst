"""End-to-end committee run for one ticker.

Fetch data -> forecast -> run the five analysts independently -> deterministic
consensus -> PM synthesis -> markdown report (+ optional SQLite persistence).
Each analyst is isolated: if one errors (e.g. a flaky web search), the run still
completes and the report says who was excluded.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from equity_analyst.committee.base import AnalystContext
from equity_analyst.committee.consensus import ConsensusSummary, compute_consensus
from equity_analyst.committee.fundamental import FundamentalAnalyst
from equity_analyst.committee.news_social import NewsSocialAnalyst
from equity_analyst.committee.portfolio_manager import PMSynthesis, PortfolioManager
from equity_analyst.committee.research import ResearchAnalyst
from equity_analyst.committee.technical import TechnicalAnalyst
from equity_analyst.committee.verdict import Verdict
from equity_analyst.data.base import MarketDataSource
from equity_analyst.data.yahoo import DataUnavailable
from equity_analyst.forecast.engine import ForecastEngine
from equity_analyst.forecast.types import ForecastResult
from equity_analyst.llm.base import LLMClient
from equity_analyst.report import build_report
from equity_analyst.storage import save_forecast_rows, save_run, upsert_prices


@dataclass
class RunResult:
    ticker: str
    as_of: str
    report_md: str
    consensus: ConsensusSummary
    pm: PMSynthesis
    verdicts: list[Verdict]
    failures: list[tuple[str, str]]
    output_path: Path | None = None


@dataclass
class MarketSnapshot:
    """Everything gathered before any analyst runs: data + forecast."""

    context: AnalystContext
    forecast: ForecastResult
    prices: pd.DataFrame  # tidy daily bars — persisted so skill checks have realized prices

    @property
    def as_of(self) -> str:
        return self.forecast.as_of_date


def gather_market_data(
    ticker: str,
    *,
    data_source: MarketDataSource,
    engine: ForecastEngine | None = None,
    period: str = "5y",
    progress: Callable[[str], None] | None = None,
) -> MarketSnapshot:
    """Fetch prices/fundamentals/analyst data and run the forecast engine.

    Shared by the full-auto pipeline and the Claude-Code-native ``prep`` stage.
    """
    ticker = ticker.upper()
    engine = engine or ForecastEngine()
    say = progress or (lambda _msg: None)

    say(f"fetching market data for {ticker}…")
    prices = data_source.get_prices(ticker, period=period)
    last_price = float(prices["close"].iloc[-1]) if not prices.empty else None
    fundamentals = _safe_dict(data_source.get_fundamentals, ticker)
    analyst_info = _safe_dict(data_source.get_analyst_info, ticker)

    say("running forecast backtests (this is the slow, honest part)…")
    forecast = engine.forecast(ticker, prices)

    context = AnalystContext(
        ticker=ticker,
        last_price=last_price,
        fundamentals=fundamentals,
        analyst_info=analyst_info,
        forecast=forecast,
    )
    return MarketSnapshot(context=context, forecast=forecast, prices=prices)


def run_committee(
    ticker: str,
    *,
    data_source: MarketDataSource,
    llm: LLMClient,
    engine: ForecastEngine | None = None,
    period: str = "5y",
    output_dir: Path | None = None,
    conn: sqlite3.Connection | None = None,
    now: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> RunResult:
    ticker = ticker.upper()
    say = progress or (lambda _msg: None)

    snapshot = gather_market_data(
        ticker, data_source=data_source, engine=engine, period=period, progress=progress
    )
    context = snapshot.context
    as_of = snapshot.as_of
    last_price = context.last_price

    analysts = [
        TechnicalAnalyst(),
        FundamentalAnalyst(llm),
        NewsSocialAnalyst(llm),
        ResearchAnalyst(llm),
    ]
    verdicts: list[Verdict] = []
    failures: list[tuple[str, str]] = []
    for analyst in analysts:
        say(f"{analyst.name} analyst working…")
        try:
            verdicts.append(analyst.evaluate(context))
        except Exception as exc:  # noqa: BLE001 - one bad analyst shouldn't kill the run
            failures.append((analyst.name, str(exc)))
            say(f"{analyst.name} analyst failed ({exc}); continuing without it")

    if not verdicts:
        raise RuntimeError(f"every analyst failed for {ticker}: {failures}")

    consensus = compute_consensus(verdicts)
    say("Portfolio Manager synthesizing…")
    try:
        pm = PortfolioManager(llm).synthesize(ticker, verdicts, consensus)
    except Exception as exc:  # noqa: BLE001 - fall back to the mechanical consensus
        failures.append(("Portfolio Manager", str(exc)))
        say(f"Portfolio Manager failed ({exc}); reporting mechanical consensus")
        pm = _mechanical_pm(consensus)

    report_md = build_report(
        ticker=ticker,
        as_of=as_of,
        verdicts=verdicts,
        consensus=consensus,
        pm=pm,
        last_price=last_price,
        failures=failures,
        fundamentals=context.fundamentals,
        analyst_info=context.analyst_info,
        forecast_rows=snapshot.forecast.horizon_rows(),
    )

    output_path = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{ticker}-{as_of}.md"
        output_path.write_text(report_md)

    if conn is not None:
        _persist(conn, ticker, as_of, snapshot, consensus, pm, report_md, now)

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


def _safe_dict(fn, ticker: str) -> dict:
    try:
        return fn(ticker)
    except DataUnavailable:
        return {}


def _mechanical_pm(consensus: ConsensusSummary) -> PMSynthesis:
    """Stand-in synthesis when the PM call fails: report the mechanical blend.

    Deliberately low conviction and clearly labeled — a deterministic average is
    not a judgment call, and the report should not pretend otherwise.
    """
    rating = max(-2, min(2, round(consensus.blended_score)))
    return PMSynthesis(
        rating=int(rating),
        conviction="low",
        horizon="mixed",
        synthesis=(
            "Portfolio Manager synthesis unavailable for this run; this is the "
            f"mechanical consensus only. {consensus.headline} "
            "Treat with reduced confidence — no judgment has been applied to "
            "weigh dissents or map risks."
        ),
        key_risks=["PM synthesis failed; risks were not assessed this run."],
        horizon_fit=[],
    )


def _persist(
    conn: sqlite3.Connection,
    ticker: str,
    as_of: str,
    snapshot: MarketSnapshot,
    consensus: ConsensusSummary,
    pm: PMSynthesis,
    report_md: str,
    now: str | None,
) -> None:
    forecast = snapshot.forecast
    created_at = now or datetime.now(timezone.utc).isoformat()
    upsert_prices(conn, ticker, snapshot.prices)
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
    save_forecast_rows(conn, ticker, as_of, forecast.horizon_rows())
