"""End-to-end committee run for one ticker.

Fetch data -> forecast -> run the five analysts independently -> deterministic
consensus -> PM synthesis -> markdown report (+ optional SQLite persistence).
Each analyst is isolated: if one errors (e.g. a flaky web search), the run still
completes and the report says who was excluded.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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
from equity_analyst.storage import save_forecast_rows, save_run


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
) -> RunResult:
    ticker = ticker.upper()
    engine = engine or ForecastEngine()

    prices = data_source.get_prices(ticker, period=period)
    last_price = float(prices["close"].iloc[-1]) if not prices.empty else None
    fundamentals = _safe_dict(data_source.get_fundamentals, ticker)
    analyst_info = _safe_dict(data_source.get_analyst_info, ticker)

    forecast = engine.forecast(ticker, prices)
    as_of = forecast.as_of_date

    context = AnalystContext(
        ticker=ticker,
        last_price=last_price,
        fundamentals=fundamentals,
        analyst_info=analyst_info,
        forecast=forecast,
    )

    analysts = [
        TechnicalAnalyst(),
        FundamentalAnalyst(llm),
        NewsSocialAnalyst(llm),
        ResearchAnalyst(llm),
    ]
    verdicts: list[Verdict] = []
    failures: list[tuple[str, str]] = []
    for analyst in analysts:
        try:
            verdicts.append(analyst.evaluate(context))
        except Exception as exc:  # noqa: BLE001 - one bad analyst shouldn't kill the run
            failures.append((analyst.name, str(exc)))

    if not verdicts:
        raise RuntimeError(f"every analyst failed for {ticker}: {failures}")

    consensus = compute_consensus(verdicts)
    pm = PortfolioManager(llm).synthesize(ticker, verdicts, consensus)

    report_md = build_report(
        ticker=ticker,
        as_of=as_of,
        verdicts=verdicts,
        consensus=consensus,
        pm=pm,
        last_price=last_price,
        failures=failures,
    )

    output_path = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{ticker}-{as_of}.md"
        output_path.write_text(report_md)

    if conn is not None:
        _persist(conn, ticker, as_of, forecast, consensus, pm, report_md, now)

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


def _persist(
    conn: sqlite3.Connection,
    ticker: str,
    as_of: str,
    forecast: ForecastResult,
    consensus: ConsensusSummary,
    pm: PMSynthesis,
    report_md: str,
    now: str | None,
) -> None:
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
