"""Committee tests: verdict validation, Technical logic, LLM analysts (offline)."""

from __future__ import annotations

import pytest

from equity_analyst.committee import (
    VERDICT_SCHEMA,
    AnalystContext,
    FundamentalAnalyst,
    NewsSocialAnalyst,
    ResearchAnalyst,
    TechnicalAnalyst,
    Verdict,
    rating_from_forecast,
    verdict_from_parsed,
)
from equity_analyst.forecast.types import ForecastResult, HorizonForecast
from equity_analyst.llm.config import ROLE_FUNDAMENTAL, ROLE_NEWS_SOCIAL, ROLE_RESEARCH
from tests.fixtures.llm import FakeLLMClient


# --- Verdict -----------------------------------------------------------------


def test_verdict_labels_and_validation() -> None:
    v = Verdict("X", 2, "high", "1y", "because")
    assert v.rating_label == "Strong Buy"
    with pytest.raises(ValueError, match="out of range"):
        Verdict("X", 3, "high", "1y", "e")
    with pytest.raises(ValueError, match="conviction"):
        Verdict("X", 1, "certain", "1y", "e")


def test_verdict_from_parsed() -> None:
    v = verdict_from_parsed(
        "Fundamental",
        {"rating": -1, "conviction": "medium", "horizon": "6-12mo", "evidence": "rich valuation"},
    )
    assert v.rating == -1 and v.rating_label == "Sell" and v.analyst == "Fundamental"
    with pytest.raises(ValueError, match="no structured output"):
        verdict_from_parsed("Fundamental", None)


# --- Technical ---------------------------------------------------------------


def _horizon(label: str, exp_ret: float, beats: bool) -> HorizonForecast:
    return HorizonForecast(
        label=label,
        steps=21,
        as_of_date="2026-01-01",
        target_date="2026-02-01",
        model="Theta" if beats else "RWD",
        point=100.0,
        lower=90.0,
        upper=110.0,
        interval_level=80,
        beats_baseline=beats,
        baseline_model="RWD",
        n_backtest_windows=5 if beats else 0,
        metrics={"expected_return": exp_ret},
    )


def _forecast(exp_ret: float, beats: bool, all_beat: bool = False) -> ForecastResult:
    horizons = [
        _horizon("1d", exp_ret / 20, beats),
        _horizon("1w", exp_ret / 4, beats and all_beat),
        _horizon("1m", exp_ret, beats),
        _horizon("1y", exp_ret * 12, beats and all_beat),
    ]
    return ForecastResult(
        ticker="TEST",
        as_of_date="2026-01-01",
        last_price=100.0,
        interval_level=80,
        horizons=horizons,
        models_considered=["RWD", "Theta"],
    )


def test_technical_rating_buckets() -> None:
    assert rating_from_forecast(_forecast(0.08, True))[0] == 2  # strong up
    assert rating_from_forecast(_forecast(0.03, True))[0] == 1  # mild up
    assert rating_from_forecast(_forecast(0.0, True))[0] == 0  # flat
    assert rating_from_forecast(_forecast(-0.03, True))[0] == -1  # mild down
    assert rating_from_forecast(_forecast(-0.08, True))[0] == -2  # strong down


def test_technical_conviction_reflects_backtest_skill() -> None:
    # Drift-only at the primary horizon -> low conviction, honest evidence.
    _, conviction, _, evidence = rating_from_forecast(_forecast(0.08, beats=False))
    assert conviction == "low"
    assert "drift-only" in evidence
    # Beats baseline everywhere -> high conviction.
    _, conviction_high, _, _ = rating_from_forecast(_forecast(0.08, beats=True, all_beat=True))
    assert conviction_high == "high"


def test_technical_analyst_end_to_end() -> None:
    ctx = AnalystContext(ticker="TEST", last_price=100.0, forecast=_forecast(0.06, True))
    v = TechnicalAnalyst().evaluate(ctx)
    assert v.analyst == "Technical" and v.rating == 2
    with pytest.raises(ValueError, match="requires context.forecast"):
        TechnicalAnalyst().evaluate(AnalystContext(ticker="TEST"))


# --- LLM analysts ------------------------------------------------------------


def test_llm_analysts_are_two_phase_and_return_verdicts() -> None:
    llm = FakeLLMClient(
        verdicts={
            ROLE_FUNDAMENTAL: {
                "rating": 1,
                "conviction": "high",
                "horizon": "1y",
                "evidence": "moat",
            },
            ROLE_NEWS_SOCIAL: {
                "rating": 0,
                "conviction": "low",
                "horizon": "1mo",
                "evidence": "quiet",
            },
            ROLE_RESEARCH: {
                "rating": 2,
                "conviction": "medium",
                "horizon": "1y",
                "evidence": "upgrades",
            },
        }
    )
    ctx = AnalystContext(
        ticker="NVDA",
        last_price=123.45,
        fundamentals={"trailingPE": 30},
        analyst_info={"targetMeanPrice": 150},
    )

    for analyst, role, rating in [
        (FundamentalAnalyst(llm), ROLE_FUNDAMENTAL, 1),
        (NewsSocialAnalyst(llm), ROLE_NEWS_SOCIAL, 0),
        (ResearchAnalyst(llm), ROLE_RESEARCH, 2),
    ]:
        v = analyst.evaluate(ctx)
        assert v.rating == rating and v.analyst == analyst.name
        assert v.writeup == llm.narrative  # full analysis rides along on the verdict

        research, extraction = llm.calls[-2], llm.calls[-1]
        # Phase 1: free-form research (no schema, tools allowed) grounded on the ticker.
        assert research["role"] == role
        assert research["schema"] is None and research["allow_tools"]
        assert "NVDA" in research["prompt"]
        # Phase 2: tool-free extraction of the verdict from the writeup.
        assert extraction["role"] == role
        assert extraction["schema"] is VERDICT_SCHEMA
        assert not extraction["allow_tools"]
        assert llm.narrative in extraction["prompt"]


def test_fundamental_prompt_grounds_on_factsheet() -> None:
    llm = FakeLLMClient(
        verdicts={
            ROLE_FUNDAMENTAL: {"rating": 0, "conviction": "low", "horizon": "1y", "evidence": "x"},
        }
    )
    ctx = AnalystContext(ticker="AAPL", last_price=200.0, fundamentals={"trailingPE": 28.5})
    FundamentalAnalyst(llm).evaluate(ctx)
    research = llm.calls[-2]  # phase-1 research call carries the fact-sheet
    assert "trailingPE: 28.5" in research["prompt"] and "$200.00" in research["prompt"]


# ---------------------------------------------------------------- fact-sheet caveats


def test_fundamentals_caveats_flags_one_off_gain_and_hypergrowth() -> None:
    from equity_analyst.committee.base import fundamentals_caveats

    caveats = "\n".join(
        fundamentals_caveats(
            {
                "sector": "Communication Services",
                "profitMargins": 0.93,
                "operatingMargins": -0.32,
                "revenueGrowth": 6.8,
            }
        )
    )
    assert "one-off non-operating gain" in caveats
    assert "hypergrowth" in caveats
    assert "provider did not return the company name" in caveats


def test_fundamentals_caveats_flags_buyback_shrunken_equity() -> None:
    from equity_analyst.committee.base import fundamentals_caveats

    caveats = "\n".join(
        fundamentals_caveats(
            {
                "longName": "Apple Inc.",
                "profitMargins": 0.27,
                "operatingMargins": 0.32,
                "returnOnEquity": 1.41,
            }
        )
    )
    assert "ROE above 100%" in caveats


def test_fundamentals_caveats_quiet_on_clean_data() -> None:
    from equity_analyst.committee.base import fundamentals_caveats

    assert (
        fundamentals_caveats(
            {
                "longName": "Clean Co.",
                "profitMargins": 0.10,
                "operatingMargins": 0.12,
                "returnOnEquity": 0.18,
                "revenueGrowth": 0.08,
                "trailingPE": 22.0,
            }
        )
        == []
    )


def test_format_analyst_info_flags_missing_consensus_fields() -> None:
    from equity_analyst.committee.base import AnalystContext, format_analyst_info

    ctx = AnalystContext(
        ticker="SNOW",
        analyst_info={
            "recommendationKey": "none",
            "numberOfAnalystOpinions": 48,
            "targetMeanPrice": 292.5,
        },
    )
    assert "no consensus rating fields" in format_analyst_info(ctx)
