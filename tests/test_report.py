"""Report rendering tests."""

from __future__ import annotations

from equity_analyst.committee.consensus import compute_consensus
from equity_analyst.committee.portfolio_manager import PMSynthesis
from equity_analyst.committee.verdict import Verdict
from equity_analyst.report import build_report


def _report() -> str:
    verdicts = [
        Verdict("Technical", 1, "medium", "1m", "momentum positive"),
        Verdict("Fundamental", -1, "high", "1y", "overvalued vs peers"),
        Verdict("News/Social", 1, "low", "1mo", "quiet news"),
        Verdict("Research", 2, "medium", "1y", "targets raised"),
    ]
    consensus = compute_consensus(verdicts)
    pm = PMSynthesis(1, "medium", "6-12mo", "Net constructive despite valuation risk.",
                     ["Valuation compression", "Execution risk"])
    return build_report(ticker="NVDA", as_of="2026-07-08", verdicts=verdicts,
                        consensus=consensus, pm=pm, last_price=123.45,
                        failures=[("Research", "web search timed out")])


def test_report_has_all_sections() -> None:
    md = _report()
    assert "# NVDA — Investment Committee (2026-07-08)" in md
    assert "## Consensus" in md
    assert "Portfolio Manager — Final Call: Buy" in md
    assert "not financial advice" in md.lower()
    for name in ["Technical", "Fundamental", "News/Social", "Research"]:
        assert f"### {name}" in md
    assert "Valuation compression" in md  # key risk rendered
    assert "web search timed out" in md  # failure surfaced


def test_report_leads_with_agreement_picture() -> None:
    md = _report()
    consensus_idx = md.index("## Consensus")
    verdicts_idx = md.index("## Analyst verdicts")
    assert consensus_idx < verdicts_idx  # agreement leads, detail follows
