"""SQLite connection and schema management.

SQLite is the system of record (see CLAUDE.md). The schema grows per milestone;
this module owns table creation and is safe to call repeatedly (idempotent DDL).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_bar (
    ticker  TEXT    NOT NULL,
    date    TEXT    NOT NULL,          -- ISO date (YYYY-MM-DD)
    open    REAL,
    high    REAL,
    low     REAL,
    close   REAL,
    volume  REAL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker  TEXT    NOT NULL,
    as_of   TEXT    NOT NULL,          -- ISO timestamp of the snapshot
    data    TEXT    NOT NULL,          -- JSON blob of fundamental facts
    PRIMARY KEY (ticker, as_of)
);

-- One row per committee run: the recommendation of record.
CREATE TABLE IF NOT EXISTS committee_run (
    ticker            TEXT NOT NULL,
    as_of             TEXT NOT NULL,   -- forecast origin date
    created_at        TEXT NOT NULL,   -- ISO timestamp of the run
    pm_rating         INTEGER,
    pm_conviction     TEXT,
    consensus_leaning TEXT,
    blended_score     REAL,
    report_md         TEXT,
    PRIMARY KEY (ticker, as_of)
);

-- Per-horizon forecast, kept so forecast-vs-actual skill can be checked later.
CREATE TABLE IF NOT EXISTS forecast (
    ticker         TEXT NOT NULL,
    as_of          TEXT NOT NULL,
    label          TEXT NOT NULL,      -- 1d | 1w | 1m | 1y
    target_date    TEXT,
    model          TEXT,
    point          REAL,
    lower          REAL,
    upper          REAL,
    interval_level INTEGER,
    beats_baseline INTEGER,            -- 0/1
    n_windows      INTEGER,
    PRIMARY KEY (ticker, as_of, label)
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open (creating parent dirs as needed) and initialize the database."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist. Idempotent."""
    conn.executescript(SCHEMA)
    conn.commit()
