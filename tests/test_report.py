"""Report rendering tests."""

from __future__ import annotations

from equity_analyst.committee.consensus import compute_consensus
from equity_analyst.committee.portfolio_manager import PMSynthesis
from equity_analyst.committee.verdict import Verdict
from equity_analyst.report import build_report


_FORECAST_ROWS = [
    {"label": "1d", "target_date": "2026-07-09", "model": "AutoETS", "point": 124.0,
     "lower": 121.0, "upper": 127.0, "interval_level": 80, "beats_baseline": True,
     "n_windows": 16},
    {"label": "1y", "target_date": "2027-07-08", "model": "RWD", "point": 135.0,
     "lower": 90.0, "upper": 180.0, "interval_level": 80, "beats_baseline": False,
     "n_windows": 16},
]


def _report() -> str:
    verdicts = [
        Verdict("Technical", 1, "medium", "1m", "momentum positive"),
        Verdict("Fundamental", -1, "high", "1y", "overvalued vs peers",
                writeup="Full fundamental writeup with valuation detail."),
        Verdict("News/Social", 1, "low", "1mo", "quiet news"),
        Verdict("Research", 2, "medium", "1y", "targets raised"),
    ]
    consensus = compute_consensus(verdicts)
    pm = PMSynthesis(1, "medium", "6-12mo", "Net constructive despite valuation risk.",
                     ["Valuation compression", "Execution risk"],
                     ["1w: noise-dominated, no edge", "1m: constructive on catalysts",
                      "1y: Buy on fundamentals"])
    return build_report(ticker="NVDA", as_of="2026-07-08", verdicts=verdicts,
                        consensus=consensus, pm=pm, last_price=123.45,
                        failures=[("Research", "web search timed out")],
                        fundamentals={"longName": "NVIDIA Corp", "sector": "Technology",
                                      "marketCap": 3.1e12, "trailingPE": 45.2,
                                      "profitMargins": 0.32},
                        analyst_info={"recommendationKey": "buy",
                                      "numberOfAnalystOpinions": 40,
                                      "targetMeanPrice": 150.0},
                        forecast_rows=_FORECAST_ROWS)


def test_report_follows_template() -> None:
    md = _report()
    # Fixed template sections, in order.
    sections = [
        "# NVDA — Investment Committee Research Report (2026-07-08)",
        "## Company snapshot",
        "### Street view",
        "## Committee consensus",
        "## Portfolio Manager — Final Call: Buy",
        "## Analyst sections",
        "## Analysts that could not be reached",
        "## Methodology & data",
    ]
    positions = [md.index(s) for s in sections]
    assert positions == sorted(positions)


def test_report_content() -> None:
    md = _report()
    # Snapshot formatting.
    assert "| Market cap | $3.10T |" in md
    assert "| Net margin | 32.0% |" in md
    assert "| Mean price target | $150.00 |" in md
    # Forecast rendered as a structured table inside the Technical section.
    assert "| 1d | 2026-07-09 | $124.00 | $121.00 – $127.00 | +0.4% | AutoETS | beats drift | 16 |" in md
    assert "drift-only ⚠️" in md  # honest flag on the 1y row
    # PM extras and failure disclosure.
    assert "1w: noise-dominated, no edge" in md
    assert "Valuation compression" in md
    assert "web search timed out" in md
    assert "not financial advice" in md.lower()
    # Writeup renders with key points; evidence-only verdicts render evidence.
    assert "Full fundamental writeup" in md
    assert "**Key points:** overvalued vs peers" in md


def test_report_without_optional_data_still_renders() -> None:
    verdicts = [Verdict("Technical", 0, "low", "1m", "flat")]
    pm = PMSynthesis(0, "low", "1m", "Hold.")
    md = build_report(ticker="X", as_of="2026-07-08", verdicts=verdicts,
                      consensus=compute_consensus(verdicts), pm=pm)
    assert "## Company snapshot" not in md  # skipped, not broken
    assert "## Committee consensus" in md
    assert "flat" in md  # evidence fallback when no forecast rows
