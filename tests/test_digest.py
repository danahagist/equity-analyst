"""Digest tests: the qualification bar, bottom-line extraction, and assembly."""

from __future__ import annotations

from equity_analyst.committee.consensus import compute_consensus
from equity_analyst.committee.portfolio_manager import PMSynthesis
from equity_analyst.committee.verdict import Verdict
from equity_analyst.digest import (
    build_digest,
    build_qualify_report,
    check_bar,
    extract_bottom_line,
)


def _verdicts(ratings=(0, 1, 1, 1)):
    seats = ("Technical", "Fundamental", "News/Social", "Research")
    return [
        Verdict(
            analyst=s,
            rating=r,
            conviction="medium",
            horizon="1y",
            evidence=f"{s} evidence",
            writeup=f"#### Bottom Line\n{s} bottom line.",
        )
        for s, r in zip(seats, ratings)
    ]


def _pm(rating=1, conviction="medium"):
    return PMSynthesis(
        rating=rating,
        conviction=conviction,
        horizon="1y",
        synthesis="The call and why.",
        key_risks=["risk one"],
        horizon_fit=["1w: noise", "1m: noise", "1y: the case"],
    )


def _packet(ticker="TEST"):
    return {
        "ticker": ticker,
        "as_of": "2026-07-08",
        "last_price": 100.0,
        "fundamentals": {"longName": "Test Corp", "sector": "Tech", "marketCap": 5e9},
        "forecast_rows": [
            {
                "label": "1m",
                "point": 103,
                "lower": 90,
                "upper": 116,
                "beats_baseline": True,
                "target_date": "2026-08-06",
                "model": "X",
                "interval_level": 80,
                "n_windows": 16,
            },
        ],
    }


def test_bar_requires_buy_medium_and_no_split() -> None:
    good = check_bar("T", _pm(), compute_consensus(_verdicts()))
    assert good.qualifies and not good.reasons

    hold_pm = check_bar("T", _pm(rating=0), compute_consensus(_verdicts()))
    assert not hold_pm.qualifies and any("not Buy" in r for r in hold_pm.reasons)

    low_conv = check_bar("T", _pm(conviction="low"), compute_consensus(_verdicts()))
    assert not low_conv.qualifies and any("below medium" in r for r in low_conv.reasons)

    # EQT-shaped: 2 Buy / 2 Hold is a split committee — fails even with a PM Buy.
    split = check_bar("T", _pm(), compute_consensus(_verdicts((0, 1, 0, 1))))
    assert not split.qualifies and any("split" in r for r in split.reasons)

    no_pm = check_bar("T", None, compute_consensus(_verdicts()))
    assert not no_pm.qualifies and any("no PM synthesis" in r for r in no_pm.reasons)


def test_qualify_report_counts_toward_need() -> None:
    quals = [
        check_bar("AAA", _pm(), compute_consensus(_verdicts())),
        check_bar("BBB", _pm(rating=0), compute_consensus(_verdicts())),
    ]
    report = build_qualify_report(quals, need=5)
    assert "1 of 5 needed" in report
    assert "✓ **AAA**" in report and "✗ **BBB**" in report
    assert "4 more qualifying name(s) needed" in report


def test_extract_bottom_line() -> None:
    writeup = "#### Valuation\nCheap.\n\n#### Bottom Line\nBuy it.\nReally.\n"
    assert extract_bottom_line(writeup) == "Buy it.\nReally."
    assert extract_bottom_line("no headings here") is None
    assert extract_bottom_line("") is None


def test_digest_assembles_all_sections() -> None:
    entries = [{"packet": _packet(), "verdicts": _verdicts(), "pm": _pm()}]
    md = build_digest(
        entries,
        as_of="2026-07-08",
        exec_summary="The week in one paragraph.",
        etf_section="| ETF | ... |",
    )
    assert "## Executive summary" in md and "The week in one paragraph." in md
    assert "## TEST — Buy (medium conviction, 1y)" in md
    assert "Test Corp" in md and "$5.0B" in md
    assert "### Portfolio Manager synthesis" in md and "risk one" in md
    assert "### Seat verdicts" in md and "| Research | Buy (+1) |" in md
    assert "**Fundamental — bottom line:** Fundamental bottom line." in md
    assert "### Levels" in md and "not orders" in md
    assert "## Broader exposure via ETFs" in md
    assert "not financial advice" in md
    assert "**Qualifies** for the weekly five." in md


def test_digest_placeholder_when_no_exec_summary() -> None:
    entries = [{"packet": _packet(), "verdicts": _verdicts(), "pm": _pm()}]
    md = build_digest(entries, as_of="2026-07-08")
    assert "Executive summary not yet written" in md
    assert "--exec-summary-file" in md


def test_digest_survives_missing_pm() -> None:
    entries = [{"packet": _packet(), "verdicts": _verdicts(), "pm": None}]
    md = build_digest(entries, as_of="2026-07-08")
    assert "no PM call" in md and "Does not qualify" in md
