"""The structured verdict every analyst emits, and its JSON schema.

The scale is a fixed integer −2…+2 so the consensus function can operate on
comparable numbers; conviction, horizon, and evidence carry the nuance.
"""

from __future__ import annotations

from dataclasses import dataclass

RATING_LABELS: dict[int, str] = {
    -2: "Strong Sell",
    -1: "Sell",
    0: "Hold",
    1: "Buy",
    2: "Strong Buy",
}
CONVICTION_LEVELS = ("low", "medium", "high")

# JSON Schema used in the extraction pass: the verdict a written analysis
# supports (analyst name is attached by us, not the model).
VERDICT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "rating": {"type": "integer", "enum": [-2, -1, 0, 1, 2]},
        "conviction": {"type": "string", "enum": list(CONVICTION_LEVELS)},
        "horizon": {"type": "string"},
        "evidence": {
            "type": "string",
            "description": "The 3-6 key points supporting the rating, condensed "
            "from the analysis. No new claims.",
        },
    },
    "required": ["rating", "conviction", "horizon", "evidence"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class Verdict:
    """One analyst's rated recommendation."""

    analyst: str
    rating: int  # −2…+2
    conviction: str  # low | medium | high
    horizon: str
    evidence: str  # concise key supporting points
    writeup: str = ""  # the analyst's full written analysis (empty for rule-based seats)

    def __post_init__(self) -> None:
        if self.rating not in RATING_LABELS:
            raise ValueError(f"rating {self.rating!r} out of range −2…+2")
        if self.conviction not in CONVICTION_LEVELS:
            raise ValueError(f"conviction {self.conviction!r} not in {CONVICTION_LEVELS}")

    @property
    def rating_label(self) -> str:
        return RATING_LABELS[self.rating]


def verdict_from_parsed(analyst: str, parsed: dict | None, *, writeup: str = "") -> Verdict:
    """Build a :class:`Verdict` from an LLM's parsed structured output."""
    if not parsed:
        raise ValueError(f"{analyst}: no structured output returned")
    return Verdict(
        analyst=analyst,
        rating=int(parsed["rating"]),
        conviction=str(parsed["conviction"]),
        horizon=str(parsed["horizon"]),
        evidence=str(parsed["evidence"]),
        writeup=writeup,
    )
