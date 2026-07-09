"""Read/write helpers over the SQLite schema.

Thin functions rather than an ORM: the queries are simple and the explicitness
keeps the data shapes obvious. Prices round-trip through the canonical tidy frame
(:data:`~equity_analyst.data.base.PRICE_COLUMNS`).
"""

from __future__ import annotations

import json
import sqlite3

import pandas as pd

from equity_analyst.data.base import PRICE_COLUMNS


def upsert_prices(conn: sqlite3.Connection, ticker: str, prices: pd.DataFrame) -> int:
    """Insert-or-replace daily bars for ``ticker``. Returns the row count written."""
    if prices.empty:
        return 0
    missing = set(PRICE_COLUMNS) - set(prices.columns)
    if missing:
        raise ValueError(f"prices frame missing columns: {sorted(missing)}")
    rows = [
        (
            ticker,
            pd.Timestamp(row.date).date().isoformat(),
            _f(row.open),
            _f(row.high),
            _f(row.low),
            _f(row.close),
            _f(row.volume),
        )
        for row in prices.itertuples(index=False)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO price_bar "
        "(ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def load_prices(conn: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    """Return stored bars for ``ticker`` as the canonical tidy frame (may be empty)."""
    cur = conn.execute(
        "SELECT date, open, high, low, close, volume FROM price_bar WHERE ticker = ? ORDER BY date",
        (ticker,),
    )
    frame = pd.DataFrame(cur.fetchall(), columns=["date", *PRICE_COLUMNS[1:]])
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"])
    return frame


def save_fundamentals(conn: sqlite3.Connection, ticker: str, data: dict, *, as_of: str) -> None:
    """Store a fundamentals snapshot as JSON, keyed by ``(ticker, as_of)``."""
    conn.execute(
        "INSERT OR REPLACE INTO fundamentals (ticker, as_of, data) VALUES (?, ?, ?)",
        (ticker, as_of, json.dumps(data)),
    )
    conn.commit()


def load_latest_fundamentals(conn: sqlite3.Connection, ticker: str) -> dict | None:
    """Return the most recent fundamentals snapshot for ``ticker``, or ``None``."""
    cur = conn.execute(
        "SELECT data FROM fundamentals WHERE ticker = ? ORDER BY as_of DESC LIMIT 1",
        (ticker,),
    )
    row = cur.fetchone()
    return json.loads(row["data"]) if row else None


def save_run(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    as_of: str,
    created_at: str,
    pm_rating: int,
    pm_conviction: str,
    consensus_leaning: str,
    blended_score: float,
    report_md: str,
) -> None:
    """Insert-or-replace the recommendation-of-record for a run."""
    conn.execute(
        "INSERT OR REPLACE INTO committee_run (ticker, as_of, created_at, pm_rating, "
        "pm_conviction, consensus_leaning, blended_score, report_md) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ticker,
            as_of,
            created_at,
            pm_rating,
            pm_conviction,
            consensus_leaning,
            float(blended_score),
            report_md,
        ),
    )
    conn.commit()


def save_forecast_rows(conn: sqlite3.Connection, ticker: str, as_of: str, rows: list[dict]) -> int:
    """Store per-horizon forecast rows (for later forecast-vs-actual skill checks)."""
    conn.executemany(
        "INSERT OR REPLACE INTO forecast (ticker, as_of, label, target_date, model, "
        "point, lower, upper, interval_level, beats_baseline, n_windows) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                ticker,
                as_of,
                r["label"],
                r["target_date"],
                r["model"],
                r["point"],
                r["lower"],
                r["upper"],
                r["interval_level"],
                int(r["beats_baseline"]),
                r["n_windows"],
            )
            for r in rows
        ],
    )
    conn.commit()
    return len(rows)


def _f(value: object) -> float | None:
    """Coerce to float, mapping pandas/NumPy NaN and None to SQL NULL."""
    if value is None or pd.isna(value):
        return None
    return float(value)
