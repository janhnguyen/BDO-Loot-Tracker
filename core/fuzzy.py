"""Fuzzy line comparison primitives for frame alignment and voting.
Operates on any object exposing the item (canonical name or None), 
qty (int), raw (str) and name_confidence (float) attributes.

The two OCR failure modes this guards against:
  - text noise in item names ("Solder" vs "Soldier") -> SequenceMatcher ratio.
  - digit confusion in quantities (6<->8, 1<->7, ...) -> single-substitution check.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Protocol

class LineLike(Protocol):
    item: str | None
    qty: int
    raw: str
    name_confidence: float

# Digit pairs Tesseract commonly swaps on the BDO acquisition-log font. Stored as
# frozensets so membership is order-independent. Tunable without touching logic.
_CONFUSABLE_DIGITS: frozenset[frozenset[str]] = frozenset(
    frozenset(pair) for pair in ("68", "17", "56", "38", "89", "08", "06", "58", "27")
)

@dataclass(frozen=True)
class MatchConfig:
    """Thresholds controlling how lenient line comparison is."""

    name_threshold: float = 0.82   # min SequenceMatcher ratio to accept two names as equal
    qty_tolerance: int = 0         # absolute |a-b| quantity difference still treated as a match
    digit_confusion: bool = True   # treat OCR-confusable quantities as matching
    line_accept: float = 0.70      # min line_similarity to treat two lines as the same physical line
    name_weight: float = 0.6       # weight of the name component in line_similarity
    qty_weight: float = 0.4        # weight of the quantity component in line_similarity
    diff_qty_penalty: float = 0.5  # similarity multiplier when the item matches but quantity differs


def _ratio(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def digit_confusable(a: int, b: int) -> bool:
    """
    True if two distinct quantities differ only by OCR-confusable digits.
    Same number of digits, and every differing position is a known confusable
    pair (e.g. 8 vs 6, 17 vs 11, 168 vs 188).
    """
    if a == b:
        return False
    sa, sb = str(a), str(b)
    if len(sa) != len(sb):
        return False
    return all(
        frozenset((x, y)) in _CONFUSABLE_DIGITS
        for x, y in zip(sa, sb)
        if x != y
    )

def quantities_match(a: int, b: int, cfg: MatchConfig = MatchConfig()) -> tuple[bool, float]:
    """Compare two quantities. Returns (is_match, confidence in [0,1])."""
    if a == b:
        return (True, 1.0)
    if cfg.digit_confusion and digit_confusable(a, b):
        return (True, 0.75)
    if cfg.qty_tolerance and abs(a - b) <= cfg.qty_tolerance:
        # Linearly fade confidence across the tolerance band.
        return (True, max(0.0, 1.0 - abs(a - b) / (cfg.qty_tolerance + 1)))
    return (False, 0.0)

def names_match(a: str | None, b: str | None, cfg: MatchConfig = MatchConfig()) -> tuple[bool, float]:
    """Compare two canonical names. Returns (is_match, confidence in [0,1])."""
    if a is not None and a == b:
        return (True, 1.0)
    if a is None or b is None:
        return (False, 0.0)
    ratio = _ratio(a.lower(), b.lower())
    return (ratio >= cfg.name_threshold, ratio)

def _name_key(line: LineLike) -> str:
    """Best available textual key for a line's item name."""
    return line.item if line.item is not None else line.raw

def line_similarity(a: LineLike, b: LineLike, cfg: MatchConfig = MatchConfig()) -> float:
    """
    Confidence in [0,1] that two lines are the same physical loot line.
    Same item + same/confusable quantity -> high (carried-over line that scrolled).
    Same item + genuinely different quantity -> low (a different drop of that item).
    Different item -> very low.
    """
    if a.item is not None and b.item is not None:
        name_ok, name_sim = names_match(a.item, b.item, cfg)
    else:
        # At least one line is unresolved; fall back to comparing raw/canon text.
        name_sim = _ratio(_name_key(a).lower(), _name_key(b).lower())
        name_ok = name_sim >= cfg.name_threshold

    if not name_ok:
        # Different items: cap low so an overlap of mismatched lines never passes.
        return 0.5 * name_sim

    qty_ok, qty_sim = quantities_match(a.qty, b.qty, cfg)
    if qty_ok:
        return cfg.name_weight * name_sim + cfg.qty_weight * qty_sim
    # Same item, incompatible quantity -> probably a separate drop, not a carry-over.
    return cfg.diff_qty_penalty * name_sim

@dataclass
class _SimpleLine:
    """Lightweight LineLike for tests and ad-hoc comparisons."""

    item: str | None = None
    qty: int = 1
    raw: str = ""
    name_confidence: float = 1.0
