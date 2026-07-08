"""Compare the latest committee run across tickers.

Ranks the stored recommendations so a universe can be screened at a glance.
Detail lives in the per-ticker reports (outputs/); this is the index, not a
substitute for reading the dissents.
"""

from __future__ import annotations

import sqlite3

from equity_analyst.committee.verdict import RATING_LABELS

_CONVICTION_ORDER = {"high": 2, "medium": 1, "low": 0}


def load_latest_runs(conn: sqlite3.Connection, tickers: list[str] | None = None) -> list[dict]:
    """Most recent run per ticker (all tickers when none given)."""
    query = (
        "SELECT ticker, as_of, pm_rating, pm_conviction, consensus_leaning, blended_score "
        "FROM committee_run r "
        "WHERE as_of = (SELECT MAX(as_of) FROM committee_run WHERE ticker = r.ticker)"
    )
    params: tuple = ()
    if tickers:
        wanted = [t.upper() for t in tickers]
        query += f" AND ticker IN ({','.join('?' * len(wanted))})"
        params = tuple(wanted)
    rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    rows.sort(
        key=lambda r: (
            r["pm_rating"],
            _CONVICTION_ORDER.get(r["pm_conviction"], 0),
            r["blended_score"],
        ),
        reverse=True,
    )
    return rows


def build_comparison(rows: list[dict], *, requested: list[str] | None = None) -> str:
    """Render the ranked comparison as markdown."""
    if not rows:
        return (
            "No stored runs to compare — run the committee on some tickers first "
            "(`equity-analyst prep TICKER`, or `analyze` in full-auto mode)."
        )

    out = [
        "# Committee comparison — latest run per ticker",
        "",
        "| # | Ticker | PM call | Conviction | Committee leans | Blended | As of |",
        "|---|--------|---------|------------|-----------------|---------|-------|",
    ]
    for i, r in enumerate(rows, 1):
        out.append(
            f"| {i} | {r['ticker']} | {RATING_LABELS.get(r['pm_rating'], '?')} "
            f"| {r['pm_conviction']} | {r['consensus_leaning']} "
            f"| {r['blended_score']:+.2f} | {r['as_of']} |"
        )

    dates = {r["as_of"] for r in rows}
    if len(dates) > 1:
        out += [
            "",
            f"⚠️ Runs span {len(dates)} different dates ({min(dates)} … {max(dates)}) — "
            "market context shifted between them. For a clean ranking, re-run the "
            "committee on the stale tickers the same day.",
        ]
    if requested:
        missing = sorted(set(t.upper() for t in requested) - {r["ticker"] for r in rows})
        if missing:
            out += ["", f"No stored runs for: {', '.join(missing)}."]

    out += [
        "",
        "_Ranking is by PM rating, then conviction, then blended score. This is an "
        "index — read each ticker's full report in `outputs/` (especially the "
        "dissents) before acting. Not financial advice._",
    ]
    return "\n".join(out)
