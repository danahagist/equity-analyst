"""Phase 6: find ETFs with the highest exposure to a set of stocks.

Given the committee's candidate tickers, rank ETFs by how much of the fund sits
in those names — so Dana can take broader, diversified exposure to a thesis
instead of (or alongside) single names.

There's no free reverse "which ETFs hold stock X" lookup, so we sweep a curated
ETF universe (broad-market + sector + thematic, weighted toward the areas the
committee tends to surface), pull each fund's holdings, and invert. yfinance
returns only each ETF's *top* holdings, so this captures ETFs where a candidate
is a meaningful position — exactly the "highest exposure" question — while
under-counting small tail positions. The report says so; not financial advice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from equity_analyst.data.base import MarketDataSource

# Curated universe: broad, sector (SPDR), and thematic funds spanning the
# sectors the screen/committee tend to reach (semis, software, energy, gold
# miners, exchanges/financials, REITs, ad-tech/comm). Edit freely.
DEFAULT_ETF_UNIVERSE: tuple[str, ...] = (
    # broad market / large-cap
    "SPY", "IVV", "VOO", "VTI", "QQQ", "IWB", "DIA", "IWM",
    # style / growth-factor
    "VUG", "MGK", "SPYG", "MTUM", "QUAL",
    # SPDR sectors
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    # tech / semis / software / AI-thematic
    "VGT", "SMH", "SOXX", "XSD", "IGV", "SKYY", "WCLD", "FDN", "XNTK",
    "BOTZ", "ROBO", "AIQ", "IRBO", "ARKK", "ARKW", "ARKQ",
    # energy
    "XLE", "XOP", "OIH",
    # gold miners
    "GDX", "GDXJ", "RING",
    # financials / regional banks / exchanges
    "KRE", "KBWB", "IAT", "IYF",
    # real estate
    "VNQ",
)  # fmt: skip


@dataclass
class ETFExposure:
    etf: str
    matched: dict[str, float] = field(default_factory=dict)  # our-ticker -> weight fraction

    @property
    def total_weight(self) -> float:
        return sum(self.matched.values())

    @property
    def n_matched(self) -> int:
        return len(self.matched)


def build_exposure(
    tickers: list[str],
    holdings_by_etf: dict[str, dict[str, float]],
) -> list[ETFExposure]:
    """Invert ETF→holdings into per-ETF exposure to the requested tickers, ranked."""
    wanted = {t.upper() for t in tickers}
    exposures: list[ETFExposure] = []
    for etf, holdings in holdings_by_etf.items():
        matched = {sym: w for sym, w in holdings.items() if sym in wanted}
        if matched:
            exposures.append(ETFExposure(etf=etf, matched=matched))
    exposures.sort(key=lambda e: (e.total_weight, e.n_matched), reverse=True)
    return exposures


def fetch_holdings(
    etfs: list[str], *, data_source: MarketDataSource, delay: float = 0.3, progress=None
) -> tuple[dict[str, dict[str, float]], list[tuple[str, str]]]:
    """Pull holdings for each ETF; collect failures rather than aborting."""
    from equity_analyst.data.yahoo import DataUnavailable

    holdings: dict[str, dict[str, float]] = {}
    failures: list[tuple[str, str]] = []
    for i, raw in enumerate(etfs):
        etf = raw.upper()
        if progress and (i % 10 == 0 or i == len(etfs) - 1):
            progress(f"holdings {i + 1}/{len(etfs)} ({etf})")
        try:
            holdings[etf] = data_source.get_etf_holdings(etf)
        except DataUnavailable as exc:
            failures.append((etf, str(exc)))
            continue
        if delay:
            time.sleep(delay)
    return holdings, failures


def fetch_profiles(
    etfs: list[str], *, data_source: MarketDataSource, delay: float = 0.3, progress=None
) -> dict[str, str]:
    """Pull each fund's own description; missing profiles are skipped, not fatal."""
    from equity_analyst.data.yahoo import DataUnavailable

    profiles: dict[str, str] = {}
    for i, raw in enumerate(etfs):
        etf = raw.upper()
        if progress and (i % 10 == 0 or i == len(etfs) - 1):
            progress(f"profile {i + 1}/{len(etfs)} ({etf})")
        try:
            profiles[etf] = data_source.get_fund_profile(etf)
        except DataUnavailable:
            continue
        if delay:
            time.sleep(delay)
    return profiles


def build_exposure_report(
    exposures: list[ETFExposure],
    *,
    tickers: list[str],
    top: int,
    failures: list[tuple[str, str]],
    as_of: str,
    swept: int | None = None,
    descriptions: dict[str, str] | None = None,
) -> str:
    # `swept` is the true universe size (fetched OK + failures). Deriving it
    # from len(exposures) undercounts: funds that fetched fine but hold zero
    # candidates would vanish from the denominator, misstating the search.
    swept = swept if swept is not None else len(exposures) + len(failures)
    lines = [
        f"# ETF exposure to your candidates ({as_of})",
        "",
        "_Which ETFs give the most exposure to {names}. Built from each fund's "
        "TOP holdings (yfinance), so it captures funds where a name is a "
        "meaningful position and under-counts small tail weights. A broader-"
        "exposure aid, not financial advice._".format(names=", ".join(t.upper() for t in tickers)),
        "",
        f"Swept {swept} ETFs; {len(exposures)} hold at least one candidate "
        f"in their top holdings ({len(failures)} fetches failed).",
        "",
        "| # | ETF | Candidates held | Combined weight | Breakdown |",
        "|---|-----|-----------------|-----------------|-----------|",
    ]
    for i, e in enumerate(exposures[:top], start=1):
        parts = sorted(e.matched.items(), key=lambda kv: kv[1], reverse=True)
        breakdown = ", ".join(f"{sym} {w:.1%}" for sym, w in parts)
        lines.append(f"| {i} | {e.etf} | {e.n_matched} | {e.total_weight:.1%} | {breakdown} |")
    lines += [
        "",
        "Combined weight = summed top-holding weight of your candidates within each "
        "ETF (higher = more concentrated in your names).",
    ]
    if descriptions:
        from equity_analyst.digest import first_sentences

        lines += ["", "What each fund is:", ""]
        for e in exposures[:top]:
            desc = descriptions.get(e.etf)
            if desc:
                lines.append(f"- **{e.etf}** — {first_sentences(desc, n=2)}")
    return "\n".join(lines)
