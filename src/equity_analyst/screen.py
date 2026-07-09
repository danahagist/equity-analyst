"""Deterministic pre-committee screen: blended Street-gap + GARP ranking.

The funnel design (see CLAUDE.md): running the full committee on a large
universe is neither affordable nor useful, so a **cheap, LLM-free screen**
ranks the universe first and the committee runs only on the survivors.

Two pillars, blended 50/50, each built from cross-sectional percentile ranks
(rank-based scoring is deliberately robust to Yahoo's outlier-prone fields):

- **Street-gap** — where the sell-side sees unpriced value: upside to the mean
  price target, plus the consensus recommendation level. Inherits analyst
  herding; that's the pillar's known bias.
- **GARP** — growth at a reasonable price from the fundamentals themselves:
  inverse PEG (growth per unit of forward multiple), free-cash-flow margin,
  operating margin, and revenue growth. Slower-moving, coverage-independent.

A ticker needs at least one Street factor and two GARP factors to be ranked;
everything else is excluded with a reason, not silently dropped. The screen is
a heuristic pre-filter — it produces *candidates for the committee*, never a
recommendation. Honesty guardrails apply: the output says exactly that.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from equity_analyst.data.base import MarketDataSource, fetch_many

BLEND = {"street": 0.5, "garp": 0.5}
MIN_ANALYSTS = 5  # below this, target/recommendation fields are too thin to trust

STREET_FACTORS = ("target_upside", "rec_score")
GARP_FACTORS = ("inverse_peg", "fcf_margin", "operating_margin", "revenue_growth")


@dataclass
class ScreenRow:
    """Raw per-ticker inputs plus computed factor values and scores."""

    ticker: str
    name: str = ""
    sector: str = ""
    price: float | None = None
    market_cap: float | None = None
    factors: dict[str, float] = field(default_factory=dict)
    # filled by score_rows:
    street_score: float | None = None
    garp_score: float | None = None
    blended: float | None = None


def _num(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN guard


def compute_factors(fundamentals: dict, analyst_info: dict) -> dict[str, float]:
    """Derive the screen's factor values from one ticker's provider dicts."""
    factors: dict[str, float] = {}

    price = _num(fundamentals.get("currentPrice"))
    target = _num(analyst_info.get("targetMeanPrice"))
    n_analysts = _num(analyst_info.get("numberOfAnalystOpinions")) or 0
    rec_mean = _num(analyst_info.get("recommendationMean"))

    if n_analysts >= MIN_ANALYSTS:
        if price and target and price > 0:
            factors["target_upside"] = (target - price) / price
        if rec_mean is not None:
            factors["rec_score"] = -rec_mean  # 1=Strong Buy … 5=Sell; higher is better

    forward_pe = _num(fundamentals.get("forwardPE"))
    growth = _num(fundamentals.get("earningsGrowth"))
    if growth is None:
        growth = _num(fundamentals.get("revenueGrowth"))
    if forward_pe and forward_pe > 0 and growth and growth > 0:
        factors["inverse_peg"] = (growth * 100) / forward_pe

    revenue = _num(fundamentals.get("totalRevenue"))
    fcf = _num(fundamentals.get("freeCashflow"))
    if revenue and revenue > 0 and fcf is not None:
        factors["fcf_margin"] = fcf / revenue

    op = _num(fundamentals.get("operatingMargins"))
    if op is not None:
        factors["operating_margin"] = op

    rev_growth = _num(fundamentals.get("revenueGrowth"))
    if rev_growth is not None:
        factors["revenue_growth"] = rev_growth

    return factors


def _percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    """ticker -> percentile rank in [0, 1] (higher = better), average ties."""
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    n = len(ordered)
    if n == 1:
        return {ordered[0][0]: 0.5}
    ranks: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        avg_rank = (i + j) / 2 / (n - 1)
        for k in range(i, j + 1):
            ranks[ordered[k][0]] = avg_rank
        i = j + 1
    return ranks


def score_rows(rows: list[ScreenRow]) -> tuple[list[ScreenRow], list[tuple[str, str]]]:
    """Cross-sectionally rank factors, blend pillars, and sort best-first.

    Returns ``(ranked_rows, excluded)`` where excluded is ``(ticker, reason)``.
    """
    per_factor_ranks: dict[str, dict[str, float]] = {}
    for factor in STREET_FACTORS + GARP_FACTORS:
        values = {r.ticker: r.factors[factor] for r in rows if factor in r.factors}
        if values:
            per_factor_ranks[factor] = _percentile_ranks(values)

    ranked: list[ScreenRow] = []
    excluded: list[tuple[str, str]] = []
    for row in rows:
        street = [per_factor_ranks[f][row.ticker] for f in STREET_FACTORS if f in row.factors]
        garp = [per_factor_ranks[f][row.ticker] for f in GARP_FACTORS if f in row.factors]
        if not street:
            excluded.append((row.ticker, "no usable Street factors (thin/absent coverage)"))
            continue
        if len(garp) < 2:
            excluded.append((row.ticker, "fewer than two usable GARP factors"))
            continue
        row.street_score = sum(street) / len(street)
        row.garp_score = sum(garp) / len(garp)
        row.blended = BLEND["street"] * row.street_score + BLEND["garp"] * row.garp_score
        ranked.append(row)

    ranked.sort(key=lambda r: r.blended, reverse=True)
    return ranked, excluded


def run_screen(
    tickers: list[str],
    *,
    data_source: MarketDataSource,
    delay: float = 0.3,
    progress=None,
) -> tuple[list[ScreenRow], list[tuple[str, str]]]:
    """Fetch light data for each ticker and build unscored rows.

    Fetch failures are recorded and skipped — with an unofficial provider at
    universe scale, partial coverage is the normal case and must be disclosed.
    """

    def build_row(ticker: str) -> ScreenRow:
        fundamentals = data_source.get_fundamentals(ticker)
        analyst_info = data_source.get_analyst_info(ticker)
        return ScreenRow(
            ticker=ticker,
            name=str(fundamentals.get("longName", "")),
            sector=str(fundamentals.get("sector", "")),
            price=_num(fundamentals.get("currentPrice")),
            market_cap=_num(fundamentals.get("marketCap")),
            factors=compute_factors(fundamentals, analyst_info),
        )

    results, failures = fetch_many(
        tickers,
        build_row,
        delay=delay,
        progress=progress,
        label="screening",
        progress_every=25,
    )
    return list(results.values()), failures


# ---------------------------------------------------------------- universe


RUSSELL_1000_WIKITEXT_URL = (
    "https://en.wikipedia.org/w/api.php?action=parse&page=Russell_1000_Index"
    "&prop=wikitext&format=json&formatversion=2"
)
_CONSTITUENT_ROW = re.compile(r"^\|\|.+?\|\|\s*([A-Z][A-Z0-9.\-]{0,9})\s*\|\|")


def parse_wikipedia_constituents(wikitext: str) -> list[str]:
    """Extract ticker symbols from the Russell 1000 wikitext components table.

    Rows look like ``|| [[3M]] || MMM || Industrials || ...`` — the second cell
    is the symbol. (The iShares holdings CSV would be the more official source,
    but it sits behind bot protection; Wikipedia's table cites it directly.)
    """
    start = wikitext.find('id="constituents"')
    if start == -1:
        raise ValueError("no constituents table found in wikitext")
    end = wikitext.find("|}", start)
    section = wikitext[start : end if end != -1 else len(wikitext)]

    tickers: list[str] = []
    for line in section.splitlines():
        match = _CONSTITUENT_ROW.match(line.strip())
        if match:
            # Yahoo uses '-' for share classes where the index uses '.' (BRK.B).
            tickers.append(match.group(1).replace(".", "-"))
    if len(tickers) < 500:  # the Russell 1000 holds ~1000 names; far fewer = bad parse
        raise ValueError(
            f"constituents table parsed but yielded only {len(tickers)} tickers — "
            "the page layout may have changed"
        )
    return tickers


def fetch_russell1000() -> list[str]:
    """Fetch the Russell 1000 constituent list (Wikipedia components table)."""
    import json
    import urllib.request

    request = urllib.request.Request(
        RUSSELL_1000_WIKITEXT_URL, headers={"User-Agent": "equity-analyst/0.1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    return parse_wikipedia_constituents(data["parse"]["wikitext"])


# ---------------------------------------------------------------- output


def build_screen_report(
    ranked: list[ScreenRow],
    *,
    top: int,
    excluded: list[tuple[str, str]],
    failures: list[tuple[str, str]],
    as_of: str,
) -> str:
    lines = [
        f"# Screen — blended Street-gap + GARP ({as_of})",
        "",
        "_Heuristic pre-filter over provider data: candidates for a committee run, "
        "not recommendations. Scores are cross-sectional percentile ranks "
        "(50% Street-gap: target upside + consensus level; 50% GARP: inverse PEG, "
        "FCF margin, operating margin, revenue growth). Not financial advice._",
        "",
        f"Ranked {len(ranked)} of {len(ranked) + len(excluded) + len(failures)} tickers "
        f"({len(excluded)} excluded for missing factors, {len(failures)} fetch failures).",
        "",
        f"## Top {min(top, len(ranked))}",
        "",
        "| # | Ticker | Name | Sector | Blended | Street | GARP | Target upside |",
        "|---|--------|------|--------|---------|--------|------|---------------|",
    ]
    for i, row in enumerate(ranked[:top], start=1):
        upside = row.factors.get("target_upside")
        lines.append(
            f"| {i} | {row.ticker} | {row.name or '—'} | {row.sector or '—'} "
            f"| {row.blended:.3f} | {row.street_score:.3f} | {row.garp_score:.3f} "
            f"| {f'{upside:+.1%}' if upside is not None else '—'} |"
        )
    lines += [
        "",
        "Next step: run the committee on the names that interest you, e.g.",
        f"  equity-analyst prep {' '.join(r.ticker for r in ranked[: min(top, 5)])} ...",
    ]
    if failures:
        shown = ", ".join(t for t, _ in failures[:15])
        more = f" (+{len(failures) - 15} more)" if len(failures) > 15 else ""
        lines += ["", f"Fetch failures: {shown}{more}"]
    return "\n".join(lines)


def write_screen_csv(ranked: list[ScreenRow], path: Path) -> Path:
    """Persist the full scored universe (not just the top slice) for audit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "rank", "ticker", "name", "sector", "price", "market_cap",
        "blended", "street_score", "garp_score",
        *STREET_FACTORS, *GARP_FACTORS,
    ]  # fmt: skip
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for i, row in enumerate(ranked, start=1):
            writer.writerow(
                {
                    "rank": i,
                    "ticker": row.ticker,
                    "name": row.name,
                    "sector": row.sector,
                    "price": row.price,
                    "market_cap": row.market_cap,
                    "blended": row.blended,
                    "street_score": row.street_score,
                    "garp_score": row.garp_score,
                    **{f: row.factors.get(f) for f in STREET_FACTORS + GARP_FACTORS},
                }
            )
    return path
