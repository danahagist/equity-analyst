"""Render a committee run as a templated markdown research report.

The template is fixed and repeatable across tickers and runs (see CLAUDE.md):

  1. Header + disclaimer
  2. Company snapshot (grounded fact-sheet) + Street view
  3. Committee consensus — the agreement picture leads, never a single number
  4. Portfolio Manager — final call, synthesis, holding-period guidance, risks
  5. Analyst sections — Technical's forecast as a structured table; each LLM
     seat's key points + full writeup (writeups carry their own templated
     sub-headings, enforced by the seat prompts)
  6. Excluded analysts (when any)
  7. Methodology & data
"""

from __future__ import annotations

from equity_analyst.committee.consensus import ConsensusSummary
from equity_analyst.committee.portfolio_manager import PMSynthesis
from equity_analyst.committee.verdict import Verdict


def _signed(rating: int) -> str:
    """Signed rating, but plain '0' for Hold (avoids an odd '+0')."""
    return f"{rating:+d}" if rating else "0"


_DISCLAIMER = (
    "_Research assistance, not financial advice. Forecasts are probabilistic and "
    "benchmarked against a naive baseline; where a model cannot beat naive drift, "
    "the baseline is reported. Sentiment reflects news and public pages, not a "
    "real-time social feed._"
)

# Fundamentals fact-sheet: (key, label, format kind), rendered in this order.
_FUND_FIELDS: list[tuple[str, str, str]] = [
    ("longName", "Company", "str"),
    ("sector", "Sector", "str"),
    ("industry", "Industry", "str"),
    ("marketCap", "Market cap", "big_money"),
    ("currentPrice", "Price (data provider)", "money"),
    ("trailingPE", "P/E (trailing)", "ratio"),
    ("forwardPE", "P/E (forward)", "ratio"),
    ("priceToBook", "Price/book", "ratio"),
    ("totalRevenue", "Revenue (TTM)", "big_money"),
    ("revenueGrowth", "Revenue growth", "pct"),
    ("earningsGrowth", "Earnings growth", "pct"),
    ("grossMargins", "Gross margin", "pct"),
    ("operatingMargins", "Operating margin", "pct"),
    ("profitMargins", "Net margin", "pct"),
    ("returnOnEquity", "Return on equity", "pct"),
    ("totalDebt", "Total debt", "big_money"),
    ("totalCash", "Total cash", "big_money"),
    ("freeCashflow", "Free cash flow", "big_money"),
    ("debtToEquity", "Debt/equity", "ratio"),
]

_STREET_FIELDS: list[tuple[str, str, str]] = [
    ("recommendationKey", "Consensus rating", "str"),
    ("recommendationMean", "Consensus mean (1=Strong Buy…5=Sell)", "ratio"),
    ("numberOfAnalystOpinions", "Covering analysts", "int"),
    ("targetMeanPrice", "Mean price target", "money"),
    ("targetMedianPrice", "Median price target", "money"),
    ("targetHighPrice", "High target", "money"),
    ("targetLowPrice", "Low target", "money"),
]


def _fmt(value: object, kind: str) -> str:
    try:
        if kind == "str":
            return str(value)
        if kind == "int":
            return f"{int(value):,}"
        if kind == "ratio":
            return f"{float(value):,.2f}"
        if kind == "pct":
            return f"{float(value):.1%}"
        if kind == "money":
            return f"${float(value):,.2f}"
        if kind == "big_money":
            n = float(value)
            for cut, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
                if abs(n) >= cut:
                    return f"${n / cut:,.2f}{suffix}"
            return f"${n:,.0f}"
    except (TypeError, ValueError):
        pass
    return str(value)


def _facts_table(data: dict, fields: list[tuple[str, str, str]]) -> list[str]:
    rows = [
        f"| {label} | {_fmt(data[key], kind)} |"
        for key, label, kind in fields
        if data.get(key) is not None
    ]
    if not rows:
        return []
    return ["| Metric | Value |", "|--------|-------|", *rows]


def _forecast_table(forecast_rows: list[dict], last_price: float | None) -> list[str]:
    level = forecast_rows[0].get("interval_level", 80)
    out = [
        f"| Horizon | Target date | Point | {level}% interval | Exp. return "
        "| Model | Skill vs drift | Windows |",
        "|---------|-------------|-------|--------------|------------|-------|"
        "----------------|---------|",
    ]
    for r in forecast_rows:
        exp = f"{(r['point'] / last_price - 1):+.1%}" if last_price else "—"
        skill = "beats drift" if r["beats_baseline"] else "drift-only ⚠️"
        out.append(
            f"| {r['label']} | {r['target_date']} | ${r['point']:,.2f} "
            f"| ${r['lower']:,.2f} – ${r['upper']:,.2f} | {exp} "
            f"| {r['model']} | {skill} | {r['n_windows']} |"
        )
    out += [
        "",
        "_Rows marked “drift-only ⚠️” mean no model demonstrated skill beyond a "
        "random walk at that horizon in backtest — treat the point estimate as "
        "decoration around the interval._",
    ]
    return out


def build_report(
    *,
    ticker: str,
    as_of: str,
    verdicts: list[Verdict],
    consensus: ConsensusSummary,
    pm: PMSynthesis,
    last_price: float | None = None,
    failures: list[tuple[str, str]] | None = None,
    fundamentals: dict | None = None,
    analyst_info: dict | None = None,
    forecast_rows: list[dict] | None = None,
) -> str:
    out: list[str] = [
        f"# {ticker} — Investment Committee Research Report ({as_of})",
    ]
    if last_price is not None:
        out.append(f"Last price: ${last_price:,.2f}")
    out += ["", _DISCLAIMER, ""]

    # --- 2. Company snapshot -------------------------------------------------
    snapshot = _facts_table(fundamentals or {}, _FUND_FIELDS)
    if snapshot:
        out += ["## Company snapshot", "", *snapshot, ""]
    street = _facts_table(analyst_info or {}, _STREET_FIELDS)
    if street:
        out += ["### Street view", "", *street, ""]

    # --- 3. Consensus ----------------------------------------------------------
    out += [
        "## Committee consensus",
        "",
        f"**{consensus.headline}**",
        "",
        f"- Vote split: {consensus.counts['Buy']} Buy · "
        f"{consensus.counts['Hold']} Hold · {consensus.counts['Sell']} Sell",
        f"- Conviction-weighted blended score: **{consensus.blended_score:+.2f}** "
        f"(−2…+2; secondary to the agreement picture)",
        f"- Agreement: {consensus.agreement_level}",
    ]
    if consensus.dissenters:
        out.append(f"- Dissenting: {', '.join(consensus.dissenters)}")
    if failures:
        out.append(f"- ⚠️ Excluded (errored): {', '.join(name for name, _ in failures)}")

    # --- 4. Portfolio Manager ----------------------------------------------------
    out += [
        "",
        f"## Portfolio Manager — Final Call: {pm.rating_label} "
        f"(rating {_signed(pm.rating)}, {pm.conviction} conviction, {pm.horizon})",
        "",
        pm.synthesis.strip(),
    ]
    if pm.horizon_fit:
        out += ["", "**Holding-period guidance**"]
        out += [f"- {line}" for line in pm.horizon_fit]
    if pm.key_risks:
        out += ["", "**Key risks**"]
        out += [f"- {risk}" for risk in pm.key_risks]

    # --- 5. Analyst sections ----------------------------------------------------
    out += ["", "## Analyst sections", ""]
    for v in verdicts:
        out += [
            f"### {v.analyst} — {v.rating_label} "
            f"(rating {_signed(v.rating)}, {v.conviction} conviction, horizon {v.horizon})",
            "",
        ]
        if v.analyst == "Technical" and forecast_rows:
            out += [*_forecast_table(forecast_rows, last_price), ""]
        elif v.writeup:
            out += [f"**Key points:** {v.evidence.strip()}", "", v.writeup.strip(), ""]
        else:
            out += [v.evidence.strip(), ""]

    # --- 6. Excluded analysts --------------------------------------------------
    if failures:
        out += ["## Analysts that could not be reached", ""]
        out += [f"- **{name}**: {err}" for name, err in failures]
        out += [""]

    # --- 7. Methodology ---------------------------------------------------------
    out += [
        "## Methodology & data",
        "",
        "- **Committee design:** role-specialized analysts reach independent "
        "verdicts (−2 Strong Sell … +2 Strong Buy, with conviction and horizon); "
        "a deterministic function computes the agreement picture; the Portfolio "
        "Manager synthesizes and may override the mechanical blend only with "
        "justification.",
        "- **Forecast:** statistical models (drift baseline, AutoARIMA, AutoETS, "
        "Theta) plus LightGBM with conformal intervals, backtested on rolling "
        "windows; a model only displaces the naive baseline at a horizon if it "
        "wins on point error *and* calibration.",
        "- **Data:** market data via Yahoo Finance (unofficial API); sentiment "
        "from web search over news and public pages.",
        "- **Record:** every run's forecasts and price pulls are stored, so "
        "forecast-vs-actual skill is auditable (`equity-analyst skill-report`).",
    ]

    return "\n".join(out).rstrip() + "\n"
