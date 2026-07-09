"""Screen tests: factor computation, rank-based scoring, universe parsing."""

from __future__ import annotations

import pytest

from equity_analyst.screen import (
    ScreenRow,
    build_screen_report,
    compute_factors,
    parse_wikipedia_constituents,
    score_rows,
    write_screen_csv,
)


def _fundamentals(**overrides):
    base = {
        "longName": "Test Co.",
        "sector": "Technology",
        "currentPrice": 100.0,
        "marketCap": 5e10,
        "forwardPE": 20.0,
        "earningsGrowth": 0.20,
        "totalRevenue": 1e10,
        "freeCashflow": 2e9,
        "operatingMargins": 0.25,
        "revenueGrowth": 0.15,
    }
    base.update(overrides)
    return base


def _analyst(**overrides):
    base = {"recommendationMean": 2.0, "numberOfAnalystOpinions": 20, "targetMeanPrice": 120.0}
    base.update(overrides)
    return base


def test_compute_factors_full_coverage() -> None:
    factors = compute_factors(_fundamentals(), _analyst())
    assert factors["target_upside"] == pytest.approx(0.20)
    assert factors["rec_score"] == pytest.approx(-2.0)
    assert factors["inverse_peg"] == pytest.approx(1.0)  # 20% growth / 20x forward
    assert factors["fcf_margin"] == pytest.approx(0.20)


def test_compute_factors_thin_coverage_drops_street() -> None:
    factors = compute_factors(_fundamentals(), _analyst(numberOfAnalystOpinions=3))
    assert "target_upside" not in factors and "rec_score" not in factors
    assert "inverse_peg" in factors  # GARP unaffected


def test_compute_factors_negative_growth_drops_peg() -> None:
    factors = compute_factors(_fundamentals(earningsGrowth=-0.10, revenueGrowth=-0.05), _analyst())
    assert "inverse_peg" not in factors
    assert factors["revenue_growth"] == pytest.approx(-0.05)


def _row(ticker, upside, growth):
    return ScreenRow(
        ticker=ticker,
        factors=compute_factors(
            _fundamentals(earningsGrowth=growth),
            _analyst(targetMeanPrice=100.0 * (1 + upside)),
        ),
    )


def test_score_rows_ranks_cheap_high_upside_first() -> None:
    rows = [
        _row("MEH", upside=0.02, growth=0.05),
        _row("BEST", upside=0.30, growth=0.40),
        _row("MID", upside=0.10, growth=0.15),
    ]
    ranked, excluded = score_rows(rows)
    assert not excluded
    assert [r.ticker for r in ranked] == ["BEST", "MID", "MEH"]
    assert ranked[0].blended > ranked[-1].blended
    assert all(0.0 <= r.blended <= 1.0 for r in ranked)


def test_score_rows_excludes_incomplete_rows_with_reasons() -> None:
    no_street = ScreenRow(
        ticker="DARK",
        factors=compute_factors(_fundamentals(), _analyst(numberOfAnalystOpinions=1)),
    )
    no_garp = ScreenRow(ticker="THIN", factors={"target_upside": 0.5, "rec_score": -1.5})
    ranked, excluded = score_rows([_row("OK", 0.1, 0.2), no_street, no_garp])
    assert [r.ticker for r in ranked] == ["OK"]
    reasons = dict(excluded)
    assert "Street" in reasons["DARK"] and "GARP" in reasons["THIN"]


def test_report_and_csv_output(tmp_path) -> None:
    ranked, excluded = score_rows([_row("AAA", 0.2, 0.3), _row("BBB", 0.05, 0.1)])
    report = build_screen_report(
        ranked, top=1, excluded=excluded, failures=[("ZZZ", "boom")], as_of="2026-07-08"
    )
    assert "| 1 | AAA |" in report and "BBB" not in report.split("## Top")[1].split("Next")[0]
    assert "not recommendations" in report and "ZZZ" in report

    path = write_screen_csv(ranked, tmp_path / "screen.csv")
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("rank,ticker")
    assert len(text.splitlines()) == 3


_ROWS = [
    "|| [[3M]] || MMM || Industrials || Industrial Conglomerates",
    "|| [[Berkshire Hathaway]] || BRK.B || Financials || Multi-Sector Holdings",
] + [f"|| [[Company {i}]] || TK{i} || Industrials || Widgets" for i in range(510)]
_NL = chr(10)
WIKITEXT_SAMPLE = _NL.join(
    [
        "== Components ==",
        '{| class="wikitable sortable" id="constituents"',
        "|-",
        "! Company !! Symbol !! Sector !! Sub-Industry",
    ]
    + [cell for row in _ROWS for cell in ("|-", row)]
    + ["|}", "After the table."]
)


def test_parse_wikipedia_constituents() -> None:
    tickers = parse_wikipedia_constituents(WIKITEXT_SAMPLE)
    assert tickers[:2] == ["MMM", "BRK-B"]  # Yahoo-style share class
    assert len(tickers) == 512


def test_parse_wikipedia_constituents_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="constituents"):
        parse_wikipedia_constituents("<html>maintenance page</html>")
    truncated = _NL.join(WIKITEXT_SAMPLE.splitlines()[:14]) + _NL + "|}"
    with pytest.raises(ValueError, match="layout may have changed"):
        parse_wikipedia_constituents(truncated)
