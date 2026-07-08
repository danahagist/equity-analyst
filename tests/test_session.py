"""Claude-Code-native session tests: prep → verdicts file → consensus → finalize."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("statsforecast", reason="install the 'forecast' extra")

from equity_analyst.forecast.engine import EngineConfig, ForecastEngine  # noqa: E402
from equity_analyst.session import (  # noqa: E402
    consensus_briefing,
    finalize_run,
    load_packet,
    prep_packet,
)
from equity_analyst.storage import connect  # noqa: E402
from tests.fixtures import FakeDataSource  # noqa: E402

_FAST_ENGINE = ForecastEngine(config=EngineConfig(max_windows=4, use_ml=False))


def _prep(tmp_path, conn=None):
    return prep_packet(
        "test",
        data_source=FakeDataSource(days=500),
        runs_dir=tmp_path / "runs",
        engine=_FAST_ENGINE,
        conn=conn,
    )


def _write_verdicts(path, seats=("Fundamental", "News/Social", "Research"), pm=True):
    doc = {
        "verdicts": [
            {"analyst": seat, "rating": 1, "conviction": "medium", "horizon": "1y",
             "evidence": f"{seat} key points", "writeup": f"{seat} full writeup"}
            for seat in seats
        ]
    }
    if pm:
        doc["pm"] = {"rating": 1, "conviction": "medium", "horizon": "6-12mo",
                     "synthesis": "Constructive.", "key_risks": ["macro"],
                     "horizon_fit": ["1w: no edge", "1m: hold", "1y: buy"]}
    path.write_text(json.dumps(doc))


def test_prep_writes_packet_and_briefings(tmp_path) -> None:
    conn = connect(":memory:")
    result = _prep(tmp_path, conn=conn)

    assert result.ticker == "TEST" and result.packet_path.exists()
    md = result.markdown
    assert "Technical analyst" in md
    for seat in ["Fundamental", "News/Social", "Research"]:
        assert f"### {seat}" in md
    assert "equity-analyst consensus TEST" in md
    # Forecasts AND price bars persisted at prep time — skill tracking works
    # even if the session is never finalized, and later runs backfill realized
    # prices for earlier forecasts.
    assert conn.execute("SELECT COUNT(*) FROM forecast").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM price_bar").fetchone()[0] == 500

    packet = load_packet(tmp_path / "runs", "test")
    assert packet["as_of"] == result.as_of
    assert set(packet["briefings"]) == {"Fundamental", "News/Social", "Research"}
    assert packet["briefings"]["News/Social"]["web_search"] is True
    assert packet["briefings"]["Fundamental"]["web_search"] is False


def test_full_session_round_trip(tmp_path) -> None:
    conn = connect(":memory:")
    result = _prep(tmp_path)
    packet = load_packet(tmp_path / "runs", "TEST")

    _write_verdicts(result.verdicts_path)

    briefing = consensus_briefing(packet)
    assert "MECHANICAL CONSENSUS" in briefing
    assert "PORTFOLIO MANAGER BRIEFING" in briefing
    assert "Fundamental full writeup" in briefing  # PM sees the writeups

    run = finalize_run(packet, output_dir=tmp_path / "out", conn=conn,
                       now="2026-07-08T00:00:00Z")
    assert [v.analyst for v in run.verdicts] == \
        ["Technical", "Fundamental", "News/Social", "Research"]
    assert run.failures == []
    assert run.pm.synthesis == "Constructive."
    assert run.output_path is not None and run.output_path.exists()
    assert conn.execute("SELECT COUNT(*) FROM committee_run").fetchone()[0] == 1


def test_missing_seat_is_failure_not_fatal(tmp_path) -> None:
    result = _prep(tmp_path)
    packet = load_packet(tmp_path / "runs", "TEST")
    _write_verdicts(result.verdicts_path, seats=("Fundamental", "Research"))

    run = finalize_run(packet)
    assert ("News/Social", "no verdict provided in session") in run.failures
    assert len(run.verdicts) == 3
    assert "could not be reached" in run.report_md


def test_missing_pm_falls_back_to_mechanical(tmp_path) -> None:
    result = _prep(tmp_path)
    packet = load_packet(tmp_path / "runs", "TEST")
    _write_verdicts(result.verdicts_path, pm=False)

    run = finalize_run(packet)
    assert run.pm.conviction == "low"
    assert "mechanical consensus" in run.pm.synthesis


def test_invalid_verdicts_fail_loudly(tmp_path) -> None:
    result = _prep(tmp_path)
    packet = load_packet(tmp_path / "runs", "TEST")

    result.verdicts_path.write_text(json.dumps(
        {"verdicts": [{"analyst": "Fundamental", "rating": 9, "conviction": "medium",
                       "horizon": "1y", "evidence": "x"}]}
    ))
    with pytest.raises(ValueError, match="invalid verdict for Fundamental"):
        finalize_run(packet)

    result.verdicts_path.write_text(json.dumps(
        {"verdicts": [{"analyst": "Quant", "rating": 1, "conviction": "medium",
                       "horizon": "1y", "evidence": "x"}]}
    ))
    with pytest.raises(ValueError, match="unknown analyst"):
        finalize_run(packet)


def test_load_packet_missing_gives_actionable_error(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="equity-analyst prep"):
        load_packet(tmp_path / "runs", "NOPE")
