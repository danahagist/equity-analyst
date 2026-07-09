"""Export the SQLite system of record to CSV or Excel.

CSV/Excel are an export layer on top of SQLite, not the primary store (see
CLAUDE.md). ``report_md`` is excluded from run exports — the rendered reports
already live in ``outputs/`` as markdown files.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

# table name -> (export name, columns or None for all)
_TABLES: dict[str, tuple[str, str]] = {
    "committee_run": (
        "runs",
        "ticker, as_of, created_at, pm_rating, pm_conviction, consensus_leaning, blended_score",
    ),
    "forecast": ("forecasts", "*"),
    "price_bar": ("prices", "*"),
    "fundamentals": ("fundamentals", "*"),
    "screen_result": ("screens", "*"),
}


def export_tables(conn: sqlite3.Connection, out_dir: Path, *, fmt: str = "csv") -> list[Path]:
    """Write each table to ``out_dir``; returns the paths written.

    ``fmt`` is ``csv`` (one file per table) or ``xlsx`` (one workbook, one
    sheet per table — requires the ``excel`` extra / openpyxl).
    """
    if fmt not in ("csv", "xlsx"):
        raise ValueError(f"unsupported export format {fmt!r} (use csv or xlsx)")

    frames = {
        name: pd.read_sql_query(f"SELECT {cols} FROM {table}", conn)  # noqa: S608 - fixed identifiers
        for table, (name, cols) in _TABLES.items()
    }
    out_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        paths = []
        for name, frame in frames.items():
            path = out_dir / f"{name}.csv"
            frame.to_csv(path, index=False)
            paths.append(path)
        return paths

    try:
        import openpyxl  # noqa: F401 - presence check for a clear error
    except ImportError as exc:
        raise RuntimeError(
            "Excel export needs openpyxl — install with: pip install -e '.[excel]'"
        ) from exc
    path = out_dir / "equity_analyst.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in frames.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return [path]
