"""End-to-end pipeline test (offline: fake data + fake LLM, real forecast engine)."""

from __future__ import annotations

import pytest

pytest.importorskip("statsforecast", reason="install the 'forecast' extra")

from equity_analyst.llm.config import (  # noqa: E402
    ROLE_FUNDAMENTAL,
    ROLE_NEWS_SOCIAL,
    ROLE_PORTFOLIO_MANAGER,
    ROLE_RESEARCH,
)
from equity_analyst.forecast.engine import EngineConfig, ForecastEngine  # noqa: E402
from equity_analyst.pipeline import run_committee  # noqa: E402
from equity_analyst.storage import connect  # noqa: E402
from tests.fixtures import FakeDataSource  # noqa: E402
from tests.fixtures.llm import FakeLLMClient  # noqa: E402

# Pipeline tests exercise orchestration, not the engine — keep the engine light.
_FAST_ENGINE = ForecastEngine(config=EngineConfig(max_windows=4, use_ml=False))


def _llm() -> FakeLLMClient:
    return FakeLLMClient(verdicts={
        ROLE_FUNDAMENTAL: {"rating": 1, "conviction": "high", "horizon": "1y", "evidence": "moat"},
        ROLE_NEWS_SOCIAL: {"rating": 1, "conviction": "medium", "horizon": "1mo", "evidence": "news"},
        ROLE_RESEARCH: {"rating": 2, "conviction": "medium", "horizon": "1y", "evidence": "targets"},
        ROLE_PORTFOLIO_MANAGER: {"rating": 1, "conviction": "high", "horizon": "6-12mo",
                                 "synthesis": "Constructive.", "key_risks": ["macro"]},
    })


def test_run_committee_end_to_end(tmp_path) -> None:
    conn = connect(":memory:")
    result = run_committee(
        "test",
        data_source=FakeDataSource(days=500),
        engine=_FAST_ENGINE,
        llm=_llm(),
        output_dir=tmp_path,
        conn=conn,
        now="2026-07-08T00:00:00Z",
    )

    # Four verdicts (Technical + 3 LLM), no failures.
    assert result.ticker == "TEST"
    assert [v.analyst for v in result.verdicts] == \
        ["Technical", "Fundamental", "News/Social", "Research"]
    assert result.failures == []
    assert result.pm.rating == 1

    # Report written and coherent.
    assert result.output_path is not None and result.output_path.exists()
    assert "Investment Committee" in result.report_md
    assert "Portfolio Manager" in result.report_md

    # Persisted: one run row + four forecast rows.
    assert conn.execute("SELECT COUNT(*) FROM committee_run").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM forecast WHERE ticker='TEST'").fetchone()[0] == 4
    row = conn.execute("SELECT pm_rating, consensus_leaning FROM committee_run").fetchone()
    assert row["pm_rating"] == 1 and row["consensus_leaning"] == "Buy"


def test_run_survives_one_failing_analyst(tmp_path) -> None:
    # LLM returns no verdict for Research -> verdict_from_parsed raises -> excluded.
    llm = _llm()
    del llm.verdicts[ROLE_RESEARCH]
    result = run_committee(
        "TEST", data_source=FakeDataSource(days=500), engine=_FAST_ENGINE, llm=llm
    )
    assert "Research" in [name for name, _ in result.failures]
    assert len(result.verdicts) == 3  # run still completes
    assert "could not be reached" in result.report_md
