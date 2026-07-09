"""Walk-down queue tests: skill-gated veto, ordering, and honesty in the report."""

from __future__ import annotations

from equity_analyst.rank import (
    RankedCandidate,
    apply_veto,
    build_queue,
    build_rank_report,
    read_screen_csv,
)


def _row(label, point, lower, upper, beats, model="X"):
    return {
        "label": label,
        "point": point,
        "lower": lower,
        "upper": upper,
        "beats_baseline": beats,
        "target_date": "2026-08-06",
        "model": model,
        "interval_level": 80,
        "n_windows": 16,
    }


def _packet(rows, last_price=100.0, ticker="TEST"):
    return {
        "ticker": ticker,
        "as_of": "2026-07-08",
        "last_price": last_price,
        "forecast_rows": rows,
    }


def test_skilled_negative_signal_demotes() -> None:
    # NEM-shaped: the only skilled horizon (1y) shows a negative expected return.
    cand = apply_veto(
        RankedCandidate("NEM", 0.8),
        _packet(
            [
                _row("1m", 100.0, 90, 110, beats=False),
                _row("1y", 97.0, 70, 125, beats=True, model="LGB"),
            ]
        ),
    )
    assert cand.vetoed
    assert any("skilled 1y" in r and "-3.0%" in r for r in cand.veto_reasons)


def test_no_skill_negative_drift_cannot_veto() -> None:
    # Drift-only negative point: noise, so no veto in either direction.
    cand = apply_veto(
        RankedCandidate("X", 0.5),
        _packet([_row("1y", 95.0, 60, 130, beats=False)]),
    )
    assert not cand.vetoed
    assert any("no skilled forecast signals" in n for n in cand.notes)


def test_skilled_positive_signal_annotates_but_never_promotes() -> None:
    cand = apply_veto(
        RankedCandidate("MU", 0.9),
        _packet([_row("1m", 107.3, 93, 121, beats=True)]),
    )
    assert not cand.vetoed
    assert any("supportive" in n for n in cand.notes)


def test_skilled_negative_1w_annotates_but_cannot_demote() -> None:
    # APP-shaped: a skilled one-week blip is too short for the holding thesis.
    cand = apply_veto(
        RankedCandidate("APP", 0.7),
        _packet([_row("1w", 99.5, 92, 107, beats=True)]),
    )
    assert not cand.vetoed
    assert any("cautionary" in n and "1w" in n for n in cand.notes)


def test_poor_reward_risk_demotes_only_when_target_is_skilled() -> None:
    # Same numbers, different skill flag on the 1y target: only the skilled one demotes.
    rows_skilled = [_row("1m", 101, 90, 112, beats=True), _row("1y", 104, 60, 148, beats=True)]
    rows_drift = [_row("1m", 101, 90, 112, beats=True), _row("1y", 104, 60, 148, beats=False)]
    assert apply_veto(RankedCandidate("A", 0.5), _packet(rows_skilled)).vetoed
    assert not apply_veto(RankedCandidate("B", 0.5), _packet(rows_drift)).vetoed


def test_1d_horizon_is_ignored_by_the_veto() -> None:
    cand = apply_veto(
        RankedCandidate("X", 0.5),
        _packet([_row("1d", 99.0, 97, 101, beats=True), _row("1m", 103.0, 92, 114, beats=True)]),
    )
    assert not cand.vetoed  # the skilled-but-negative 1d signal does not count


def test_queue_orders_clean_by_blended_and_sinks_vetoed() -> None:
    packets = {
        "AAA": _packet([_row("1y", 97.0, 70, 125, beats=True)], ticker="AAA"),  # vetoed
        "BBB": _packet([_row("1y", 110.0, 80, 140, beats=False)], ticker="BBB"),
        "CCC": _packet([_row("1y", 115.0, 85, 145, beats=False)], ticker="CCC"),
    }
    queue = build_queue([("AAA", 0.9), ("BBB", 0.8), ("CCC", 0.7)], packets)
    assert [c.ticker for c in queue] == ["BBB", "CCC", "AAA"]
    assert queue[-1].vetoed


def test_missing_packet_is_flagged_not_dropped() -> None:
    queue = build_queue([("ZZZ", 0.6)], {})
    assert len(queue) == 1 and not queue[0].has_packet
    assert any("no prep packet" in n for n in queue[0].notes)


def test_report_shows_demotion_and_walkdown_bar(tmp_path) -> None:
    packets = {"AAA": _packet([_row("1y", 97.0, 70, 125, beats=True)], ticker="AAA")}
    report = build_rank_report(build_queue([("AAA", 0.9)], packets), as_of="2026-07-08")
    assert "DEMOTED" in report
    assert "skill-gated veto" in report
    assert "medium+ conviction" in report
    assert "not a verdict" in report


def test_read_screen_csv_takes_top_rows(tmp_path) -> None:
    path = tmp_path / "screen.csv"
    path.write_text("rank,ticker,blended\n1,aaa,0.91\n2,BBB,0.85\n3,CCC,0.80\n", encoding="utf-8")
    assert read_screen_csv(path, top=2) == [("AAA", 0.91), ("BBB", 0.85)]
