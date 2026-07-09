"""Consensus function tests (deterministic)."""

from __future__ import annotations

import pytest

from equity_analyst.committee.consensus import compute_consensus
from equity_analyst.committee.verdict import Verdict


def _v(name: str, rating: int, conviction: str = "medium") -> Verdict:
    return Verdict(name, rating, conviction, "1y", f"{name} evidence")


def test_unanimous_buy() -> None:
    c = compute_consensus([_v(f"A{i}", 1) for i in range(5)])
    assert c.leaning == "Buy"
    assert c.agreement_level == "unanimous"
    assert c.dissenters == []
    assert c.counts == {"Buy": 5, "Hold": 0, "Sell": 0}


def test_majority_with_dissent() -> None:
    verdicts = [
        _v("Technical", 1),
        _v("Fundamental", -1),
        _v("News/Social", 1),
        _v("Research", 2),
        _v("PM", 1),
    ]
    c = compute_consensus(verdicts)
    assert c.leaning == "Buy"
    assert c.agreement_level == "strong"  # 4 of 5 == ceil(2*5/3)
    assert c.dissenters == ["Fundamental"]
    assert "Fundamental dissents (Sell)" in c.headline


def test_split_when_tied() -> None:
    c = compute_consensus([_v("A", 2), _v("B", 1), _v("C", -1), _v("D", -2), _v("E", 0)])
    assert c.leaning == "Split"
    assert c.dissenters == []
    assert "divided" in c.headline


def test_blended_score_weights_by_conviction() -> None:
    # +2 at high (w=3) vs -2 at low (w=1): (2*3 + -2*1)/(3+1) = 1.0
    c = compute_consensus([_v("A", 2, "high"), _v("B", -2, "low")])
    assert c.blended_score == 1.0


def test_empty_raises() -> None:
    with pytest.raises(ValueError, match="zero verdicts"):
        compute_consensus([])
