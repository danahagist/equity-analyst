"""Phase 4: entry/exit levels as decision support (NOT auto-execution).

Derives a buy/trim/stop plan for a ticker from the forecast engine's
**calibrated 80% intervals** — deliberately not from the skill-less point
"upside" and not from classic chart TA (support/resistance, moving averages),
both of which the tool rejects on honesty grounds (see CLAUDE.md).

The philosophy, per Dana's mandate: capture a *meaningful* share of the upside
and rotate — not squeeze the top. So exits are a laddered take-profit (trim at
the near-term upside band, exit the rest at the longer-horizon target), and the
stop sits just below the near-term downside band as risk control. Every plan
carries the forecast's skill flags: where a horizon didn't beat naive drift,
the level is framed as drift-only and the interval is what matters.

These are a framework for a human to act on, not advice and not orders.
"""

from __future__ import annotations

from dataclasses import dataclass

_NEAR_HORIZONS = ("1m", "1w", "1d")  # preference order for the near-term band
_TARGET_HORIZONS = ("1y", "1m")  # preference order for the longer take-profit


@dataclass(frozen=True)
class LevelPlan:
    ticker: str
    as_of: str
    last_price: float
    near_label: str
    near_beats_drift: bool
    target_label: str
    target_beats_drift: bool
    buy_below: float  # accumulate at or under this (near-term downside band)
    fair_value: float  # near-term point estimate — reference, not a signal
    trim_near: float  # first take-profit (near-term upside band)
    target: float  # exit the rest here (longer-horizon estimate)
    stop: float  # risk stop, below the near-term downside band
    notes: str

    @property
    def upside_to_target_pct(self) -> float:
        return (self.target - self.last_price) / self.last_price

    @property
    def downside_to_stop_pct(self) -> float:
        return (self.last_price - self.stop) / self.last_price

    @property
    def reward_risk(self) -> float | None:
        down = self.downside_to_stop_pct
        return (self.upside_to_target_pct / down) if down > 0 else None


def _pick(rows: dict[str, dict], order: tuple[str, ...]) -> dict | None:
    for label in order:
        if label in rows:
            return rows[label]
    return None


def plan_from_packet(packet: dict) -> LevelPlan:
    """Build a :class:`LevelPlan` from a prep packet (last_price + forecast_rows).

    Raises ValueError for any malformed packet (missing/None price, no rows) so
    callers have one exception type for "this packet can't produce levels".
    """
    if packet.get("last_price") is None:
        raise ValueError(f"{packet.get('ticker')}: packet has no last price")
    last_price = float(packet["last_price"])
    rows = {r["label"]: r for r in packet.get("forecast_rows", [])}
    if not rows:
        raise ValueError(f"{packet.get('ticker')}: packet has no forecast rows")

    near = _pick(rows, _NEAR_HORIZONS)
    if near is None:
        raise ValueError(f"{packet.get('ticker')}: no near-term horizon in forecast")
    target_row = _pick(rows, _TARGET_HORIZONS) or near

    lower, point, upper = float(near["lower"]), float(near["point"]), float(near["upper"])
    # Stop sits half a downside-band below the 80% lower bound: a break past it
    # means price has moved outside the range the model deemed likely.
    stop = lower - 0.5 * (point - lower)
    target = float(target_row["point"])

    near_beats = bool(near["beats_baseline"])
    target_beats = bool(target_row["beats_baseline"])
    caveats = []
    if not near_beats:
        caveats.append(
            f"near-term ({near['label']}) forecast did not beat naive drift — treat "
            "the band as a volatility range, not a directional call"
        )
    if not target_beats:
        caveats.append(
            f"target ({target_row['label']}) is drift-only; the interval is wide and "
            "the point is an extrapolation, not a skillful price prediction"
        )
    if target <= last_price:
        caveats.append(
            "longer-horizon estimate is at or below the current price — no positive "
            "expected drift; this is a risk-management plan, not an entry thesis"
        )
    notes = "; ".join(caveats) if caveats else "near-term model beat drift; band is meaningful"

    return LevelPlan(
        ticker=str(packet["ticker"]),
        as_of=str(packet["as_of"]),
        last_price=last_price,
        near_label=str(near["label"]),
        near_beats_drift=near_beats,
        target_label=str(target_row["label"]),
        target_beats_drift=target_beats,
        buy_below=round(lower, 2),
        fair_value=round(point, 2),
        trim_near=round(upper, 2),
        target=round(target, 2),
        stop=round(stop, 2),
        notes=notes,
    )


def build_levels_report(plans: list[LevelPlan], *, as_of: str) -> str:
    lines = [
        f"# Entry / exit levels — decision support ({as_of})",
        "",
        "_Derived from the forecast's calibrated 80% intervals, not chart TA. A "
        "framework for a human to act on — NOT financial advice and NOT trade "
        "orders. Where a horizon didn't beat naive drift, the band is a volatility "
        "range, not a directional call. Goal: capture meaningful upside and rotate, "
        "not top-tick._",
        "",
        "| Ticker | Price | Buy ≤ | Fair | Trim ≈ | Target | Stop | Upside | R:R |",
        "|--------|-------|-------|------|--------|--------|------|--------|-----|",
    ]
    for p in plans:
        rr = p.reward_risk
        lines.append(
            f"| {p.ticker} | ${p.last_price:,.2f} | ${p.buy_below:,.2f} "
            f"| ${p.fair_value:,.2f} | ${p.trim_near:,.2f} | ${p.target:,.2f} "
            f"| ${p.stop:,.2f} | {p.upside_to_target_pct:+.1%} "
            f"| {f'{rr:.1f}' if rr is not None else '—'} |"
        )
    lines += ["", "Per-ticker notes:"]
    lines += [f"- **{p.ticker}** ({p.near_label} band): {p.notes}" for p in plans]
    return "\n".join(lines)
