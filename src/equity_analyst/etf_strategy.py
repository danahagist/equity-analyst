"""ETF strategy: a coverage-optimized fund basket over the screen's top names.

Dana's use case: get exposure to the *opportunity set* the screen surfaced
without depending on single-name selection (or on the forecaster having skill).
Given the top-N screened names and an ETF universe, greedily build a small
basket where each added fund maximizes *marginal* coverage of the names not yet
covered — overlap-aware by construction, so "buy several ETFs" doesn't quietly
become "buy NVDA five times." Then attach historical risk/return statistics
per basket fund.

Honesty constraints, stated in the report because they shape the answer:

- yfinance exposes only each fund's TOP holdings, so coverage is systematically
  understated — a broad index fund holding 40 of the 50 names in its tail looks
  like it holds 3. The analysis therefore favors funds where the screen's names
  are *meaningful* positions, which is the interesting question anyway.
- An ETF buys the whole fund: taking SMH for its NVDA/MU/AVGO weight is a
  semiconductor-sector bet, not three stock bets.
- ETF exposure deliberately dilutes the stock-level signal the screen ranked
  on — that is the trade being chosen, and it is stated, not hidden.
- All statistics are computed from price history: a description of the past,
  not a forecast. Expense ratios are not available from the data provider.

Decision support, not financial advice, and never orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from equity_analyst.data.base import MarketDataSource

TRADING_DAYS = 252


@dataclass
class BasketPick:
    etf: str
    # names newly covered by this pick (not covered by earlier picks): ticker -> fund weight
    marginal: dict[str, float]
    # every screened name this fund holds, incl. overlap with earlier picks
    all_matched: dict[str, float]
    gain: float  # blended-score mass added by this pick

    @property
    def overlap(self) -> dict[str, float]:
        return {t: w for t, w in self.all_matched.items() if t not in self.marginal}


def _candidate_scores(candidates: list[tuple[str, float | None]]) -> dict[str, float]:
    """Ticker -> score for the set-cover. Unscored names get the mean of the
    real scores (not 1.0 — the percentile maximum — which would let a hand-typed
    extra ticker outweigh every genuinely screened name), or 1.0 only when no
    candidate is scored at all (plain-tickers invocation: equal weights).
    """
    known = [b for _, b in candidates if b is not None]
    default = sum(known) / len(known) if known else 1.0
    return {t.upper(): (b if b is not None else default) for t, b in candidates}


def build_basket(
    candidates: list[tuple[str, float | None]],
    holdings_by_etf: dict[str, dict[str, float]],
    *,
    max_etfs: int = 5,
) -> tuple[list[BasketPick], list[str]]:
    """Greedy set-cover: each pick maximizes blended-score mass newly covered.

    Returns ``(picks, uncovered)`` where uncovered lists screened names no
    basket fund holds (in its top holdings). Ties break toward the fund with
    more in-fund weight in the marginal names.
    """
    scores = _candidate_scores(candidates)
    matched_by_etf = {
        etf: {sym: w for sym, w in holdings.items() if sym in scores}
        for etf, holdings in holdings_by_etf.items()
    }

    picks: list[BasketPick] = []
    picked: set[str] = set()
    covered: set[str] = set()
    for _ in range(max_etfs):
        best: tuple[tuple[float, float, str], dict[str, float]] | None = None
        for etf, matched in matched_by_etf.items():
            if etf in picked:
                continue
            marginal = {t: w for t, w in matched.items() if t not in covered}
            if not marginal:
                continue
            gain = sum(scores[t] for t in marginal)
            key = (gain, sum(marginal.values()), etf)
            if best is None or key > best[0]:
                best = (key, marginal)
        if best is None:
            break  # nothing adds coverage — stop early rather than pad the basket
        (gain, _, etf), marginal = best
        picks.append(
            BasketPick(etf=etf, marginal=marginal, all_matched=matched_by_etf[etf], gain=gain)
        )
        picked.add(etf)
        covered |= set(marginal)

    uncovered = [t for t, _ in candidates if t.upper() not in covered]
    return picks, uncovered


# ---------------------------------------------------------------- statistics


@dataclass
class ETFStats:
    etf: str
    years: float = 0.0  # span of history the stats cover
    total_return_1y: float | None = None
    cagr: float | None = None  # over the full fetched span
    ann_vol: float | None = None
    max_drawdown: float | None = None
    beta_vs_spy: float | None = None
    return_over_vol: float | None = None  # CAGR / ann_vol; NOT a Sharpe ratio (no rf)
    error: str | None = None
    _returns: pd.Series | None = field(default=None, repr=False)


def compute_stats(prices: pd.DataFrame, spy_returns: pd.Series | None) -> dict:
    """Historical risk/return from a tidy daily price frame (close column)."""
    closes = prices.set_index("date")["close"].astype(float)
    returns = closes.pct_change().dropna()
    if len(returns) < 60:  # under ~3 months of history the numbers are noise
        return {"error": f"only {len(returns)} daily returns — too short for stats"}

    years = len(returns) / TRADING_DAYS
    cagr = (closes.iloc[-1] / closes.iloc[0]) ** (1 / years) - 1
    ann_vol = float(returns.std() * (TRADING_DAYS**0.5))
    running_max = closes.cummax()
    max_dd = float((closes / running_max - 1).min())
    total_1y = (
        float(closes.iloc[-1] / closes.iloc[-TRADING_DAYS] - 1)
        if len(closes) > TRADING_DAYS
        else None
    )
    beta = None
    if spy_returns is not None:
        joined = pd.concat([returns, spy_returns], axis=1, join="inner").dropna()
        joined = joined.tail(TRADING_DAYS)  # beta over the most recent year
        if len(joined) >= 60 and float(joined.iloc[:, 1].var()) > 0:
            beta = float(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / joined.iloc[:, 1].var())

    return {
        "years": round(years, 1),
        "total_return_1y": total_1y,
        "cagr": float(cagr),
        "ann_vol": ann_vol,
        "max_drawdown": max_dd,
        "beta_vs_spy": beta,
        "return_over_vol": float(cagr) / ann_vol if ann_vol else None,
        "returns": returns,
    }


def fetch_stats(
    etfs: list[str],
    *,
    data_source: MarketDataSource,
    period: str = "5y",
    delay: float = 0.3,
    progress=None,
) -> list[ETFStats]:
    """Pull price history for SPY + each basket fund and compute statistics."""
    from equity_analyst.data.base import DataUnavailable, fetch_many

    if not etfs:
        return []  # don't spend a SPY fetch when there's nothing to benchmark

    spy_returns: pd.Series | None = None
    try:
        spy = data_source.get_prices("SPY", period=period)
        spy_returns = spy.set_index("date")["close"].astype(float).pct_change().dropna()
    except DataUnavailable:
        pass  # betas become "—"; disclosed by their absence

    frames, failures = fetch_many(
        etfs,
        lambda etf: data_source.get_prices(etf, period=period),
        delay=delay,
        progress=progress,
        label="stats",
        progress_every=1,
    )
    failure_reasons = dict(failures)

    out: list[ETFStats] = []
    for etf in (str(e).upper() for e in etfs):
        if etf in failure_reasons:
            out.append(ETFStats(etf=etf, error=failure_reasons[etf]))
            continue
        stats = compute_stats(frames[etf], spy_returns)
        if "error" in stats:
            out.append(ETFStats(etf=etf, error=stats["error"]))
        else:
            out.append(ETFStats(etf=etf, _returns=stats.pop("returns"), **stats))
    return out


def basket_correlations(stats: list[ETFStats]) -> list[tuple[str, str, float]]:
    """Pairwise daily-return correlations between basket funds (diversification check)."""
    pairs: list[tuple[str, str, float]] = []
    usable = [s for s in stats if s._returns is not None]
    for i, a in enumerate(usable):
        for b in usable[i + 1 :]:
            joined = pd.concat([a._returns, b._returns], axis=1, join="inner").dropna()
            if len(joined) >= 60:
                pairs.append((a.etf, b.etf, float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))))
    return pairs


# ---------------------------------------------------------------- report


def _pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "—"
    return f"{value:+.1%}" if signed else f"{value:.1%}"


def build_strategy_report(
    picks: list[BasketPick],
    stats: list[ETFStats],
    *,
    candidates: list[tuple[str, float | None]],
    uncovered: list[str],
    correlations: list[tuple[str, str, float]],
    swept: int,
    as_of: str,
    descriptions: dict[str, str] | None = None,
) -> str:
    n = len(candidates)
    covered_names = n - len(uncovered)
    # Same score semantics as build_basket, so the reported mass matches the
    # greedy decisions; guard the all-zero-scores edge (percentile ranks can
    # legitimately be 0.0) instead of dividing by zero.
    total_mass = sum(_candidate_scores(candidates).values())
    covered_mass = sum(p.gain for p in picks)
    mass_text = f" ({covered_mass / total_mass:.0%} of blended-score mass)" if total_mass else ""

    lines = [
        f"# ETF strategy — coverage of the screen's top {n} ({as_of})",
        "",
        "_A coverage-optimized fund basket over the screened opportunity set: each "
        "fund was picked for the names the earlier picks do NOT already cover. "
        "Read the caveats: (1) provider data shows only each fund's TOP holdings, "
        "so coverage is understated and tail positions are invisible; (2) an ETF "
        "buys the whole fund — sector exposure, not stock picks; (3) taking ETF "
        "exposure deliberately dilutes the stock-level signal the screen ranked "
        "on; (4) all statistics are history, not forecasts, and expense ratios "
        "are not available from the provider. Decision support, not financial "
        "advice, and not orders._",
        "",
        f"Swept {swept} funds. The basket covers **{covered_names} of {n}** screened "
        f"names{mass_text} via their top holdings.",
        "",
        "## The basket",
        "",
        "| # | ETF | New names covered | Marginal weight | Coverage detail |",
        "|---|-----|-------------------|-----------------|-----------------|",
    ]
    for i, p in enumerate(picks, start=1):
        detail = ", ".join(
            f"{t} {w:.1%}" for t, w in sorted(p.marginal.items(), key=lambda kv: -kv[1])[:8]
        )
        if len(p.marginal) > 8:
            detail += f" (+{len(p.marginal) - 8} more)"
        lines.append(
            f"| {i} | {p.etf} | {len(p.marginal)} | {sum(p.marginal.values()):.1%} | {detail} |"
        )

    if descriptions:
        from equity_analyst.digest import first_sentences

        lines += ["", "### What each fund is", ""]
        for p in picks:
            desc = descriptions.get(p.etf)
            lines.append(
                f"- **{p.etf}** — "
                + (
                    first_sentences(desc, n=3)
                    if desc
                    else "no fund description available from the provider."
                )
            )

    overlaps = [(p.etf, p.overlap) for p in picks if p.overlap]
    if overlaps:
        lines += ["", "Overlap already covered by earlier picks (double-exposure to watch):"]
        lines += [
            f"- **{etf}** also holds {', '.join(f'{t} {w:.1%}' for t, w in ov.items())}"
            for etf, ov in overlaps
        ]

    lines += [
        "",
        "## Risk & return (historical)",
        "",
        "_Backward-looking by construction. Return/vol is CAGR divided by annualized "
        "volatility — not a Sharpe ratio (no risk-free adjustment). Beta is vs SPY "
        "over the most recent year of overlapping daily returns._",
        "",
        "| ETF | Span | 1y return | CAGR | Ann. vol | Max drawdown | Beta (SPY) | Ret/Vol |",
        "|-----|------|-----------|------|----------|--------------|------------|---------|",
    ]
    for s in stats:
        if s.error:
            lines.append(f"| {s.etf} | — | stats unavailable: {s.error} | | | | | |")
            continue
        rv = f"{s.return_over_vol:.2f}" if s.return_over_vol is not None else "—"
        beta = f"{s.beta_vs_spy:.2f}" if s.beta_vs_spy is not None else "—"
        lines.append(
            f"| {s.etf} | {s.years:.1f}y | {_pct(s.total_return_1y)} | {_pct(s.cagr)} "
            f"| {_pct(s.ann_vol, signed=False)} | {_pct(s.max_drawdown)} | {beta} | {rv} |"
        )

    if correlations:
        lines += [
            "",
            "Pairwise daily-return correlation (lower = more genuine diversification):",
            "",
        ]
        lines += [f"- {a} / {b}: {corr:+.2f}" for a, b, corr in correlations]

    if uncovered:
        lines += [
            "",
            f"## Not covered ({len(uncovered)} of {n})",
            "",
            "Screened names no basket fund holds in its top holdings — single-name "
            "exposure is the only direct route to these (or they sit in fund tails "
            "this data cannot see): " + ", ".join(uncovered) + ".",
        ]

    lines += [
        "",
        "_This tool provides research assistance, not financial advice._",
    ]
    return "\n".join(lines)
