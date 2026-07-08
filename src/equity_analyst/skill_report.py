"""Forecast-vs-actual skill report — the tool auditing its own forecaster.

Every run stores its per-horizon forecasts (at prep/analyze time) and the
price history it pulled. Once a forecast's target date has passed, later runs'
price pulls contain the realized price — so the evaluation data accumulates
automatically. This module joins the two and answers, per horizon:

- **Coverage**: do the 80% intervals contain reality ~80% of the time?
  (Well below nominal = overconfident — the serious failure.)
- **Point skill**: does the model beat a naive last-price forecast?
- **Claimed skill**: restricted to forecasts where the backtest claimed
  `beats_baseline` — the rows actually on trial.

Honesty rules: consecutive runs share overlapping outcome windows, so samples
are not independent; and below ~30 resolved forecasts per horizon the report
says the sample is too small to conclude anything.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

MIN_CONCLUSIVE_N = 30
_LABEL_ORDER = {"1d": 0, "1w": 1, "1m": 2, "1y": 3}


@dataclass
class ResolvedForecast:
    ticker: str
    as_of: str
    label: str
    target_date: str
    model: str
    point: float
    lower: float
    upper: float
    interval_level: int
    beats_baseline: bool
    base_price: float  # close at as_of (the naive forecast)
    realized: float  # first close on/after target_date


def resolve_forecasts(
    conn: sqlite3.Connection, *, today: str, ticker: str | None = None
) -> tuple[list[ResolvedForecast], int]:
    """Join matured forecasts with realized prices. Returns (resolved, unresolvable)."""
    query = "SELECT * FROM forecast WHERE target_date <= ?"
    params: list = [today]
    if ticker:
        query += " AND ticker = ?"
        params.append(ticker.upper())

    resolved: list[ResolvedForecast] = []
    unresolvable = 0
    for row in conn.execute(query, params).fetchall():
        base = conn.execute(
            "SELECT close FROM price_bar WHERE ticker = ? AND date <= ? "
            "ORDER BY date DESC LIMIT 1",
            (row["ticker"], row["as_of"]),
        ).fetchone()
        realized = conn.execute(
            "SELECT close FROM price_bar WHERE ticker = ? AND date >= ? "
            "ORDER BY date ASC LIMIT 1",
            (row["ticker"], row["target_date"]),
        ).fetchone()
        if base is None or base["close"] is None or realized is None or realized["close"] is None:
            unresolvable += 1
            continue
        resolved.append(
            ResolvedForecast(
                ticker=row["ticker"],
                as_of=row["as_of"],
                label=row["label"],
                target_date=row["target_date"],
                model=row["model"],
                point=row["point"],
                lower=row["lower"],
                upper=row["upper"],
                interval_level=row["interval_level"],
                beats_baseline=bool(row["beats_baseline"]),
                base_price=base["close"],
                realized=realized["close"],
            )
        )
    return resolved, unresolvable


def _aggregate(rows: list[ResolvedForecast]) -> dict:
    n = len(rows)
    covered = sum(1 for r in rows if r.lower <= r.realized <= r.upper)
    mae_model = sum(abs(r.point - r.realized) for r in rows) / n
    mae_naive = sum(abs(r.base_price - r.realized) for r in rows) / n
    return {
        "n": n,
        "coverage": covered / n,
        "nominal": sum(r.interval_level for r in rows) / n / 100.0,
        "mae_model": mae_model,
        "mae_naive": mae_naive,
        "skill_ratio": mae_model / mae_naive if mae_naive else float("inf"),
    }


def build_skill_report(
    resolved: list[ResolvedForecast], *, unresolvable: int, today: str
) -> str:
    """Render the audit as markdown."""
    out = [f"# Forecast skill report (as of {today})", ""]
    if not resolved:
        out += [
            "No matured forecasts to evaluate yet. Forecasts resolve when their "
            "target date passes AND a later run's price pull contains that date — "
            "keep running the committee on a cadence and check back.",
        ]
        if unresolvable:
            out += [
                "",
                f"({unresolvable} matured forecast(s) lack realized prices so far; "
                "the next run on those tickers will backfill them.)",
            ]
        return "\n".join(out)

    def table(rows: list[ResolvedForecast], title: str) -> list[str]:
        by_label: dict[str, list[ResolvedForecast]] = {}
        for r in rows:
            by_label.setdefault(r.label, []).append(r)
        lines = [
            f"## {title}",
            "",
            "| Horizon | n | Coverage (nominal) | MAE model | MAE naive | Skill ratio |",
            "|---------|---|--------------------|-----------|-----------|-------------|",
        ]
        for label in sorted(by_label, key=lambda x: _LABEL_ORDER.get(x, 9)):
            a = _aggregate(by_label[label])
            flag = " ⚠️ small sample" if a["n"] < MIN_CONCLUSIVE_N else ""
            lines.append(
                f"| {label} | {a['n']}{flag} | {a['coverage']:.0%} ({a['nominal']:.0%}) "
                f"| {a['mae_model']:.2f} | {a['mae_naive']:.2f} "
                f"| {a['skill_ratio']:.3f} |"
            )
        return lines + [""]

    out += table(resolved, "All resolved forecasts")

    claimed = [r for r in resolved if r.beats_baseline]
    if claimed:
        out += table(
            claimed,
            "Forecasts that claimed skill in backtest (`beats_baseline`) — on trial",
        )

    out += [
        "## How to read this",
        "",
        "- **Coverage** should track nominal (~80%). Meaningfully lower = the "
        "intervals are overconfident; treat them as wider than printed. Higher = "
        "honest but conservative.",
        "- **Skill ratio** < 1 means the selected models beat a naive last-price "
        "forecast out of sample; ≥ 1 means they don't — which is the expected "
        "outcome for efficient markets and exactly what this tool is designed to "
        "admit. Weight the qualitative seats accordingly.",
        "- Samples from consecutive runs overlap in time and are **not "
        "independent** — don't treat small differences as significant.",
        f"- Rows flagged ⚠️ have fewer than {MIN_CONCLUSIVE_N} resolved forecasts: "
        "suggestive at best, not conclusive.",
    ]
    if unresolvable:
        out += [
            "",
            f"({unresolvable} matured forecast(s) still lack a realized price; the "
            "next committee run on those tickers will backfill it.)",
        ]
    return "\n".join(out)
