"""
OCR normalization: raw acquisition-log text -> canonical loot lines.

A NormalizedLine carries the canonical item name, the parsed quantity,
the original raw text, and a confidence for how the name was resolved. 
Resolution order:

  1. exact substring match against the known-item dictionary
  2. fuzzy match against the dictionary when (1) misses ("Ancient Solder
     Fragment" -> "Ancient Soldier Fragment").

Unresolved lines are still returned with item=None so frame alignment can fall
back to comparing their raw text.
"""
from __future__ import annotations
from dataclasses import dataclass
from .parser import (
    _clean_line,
    _parse_single_line,
    _QTY_RE,
    extract_quantity,
    fuzzy_resolve_name,
)

# Default fuzzy acceptance for name resolution (kept aligned with MatchConfig).
FUZZY_NAME_THRESHOLD = 0.82

@dataclass(frozen=True)
class NormalizedLine:
    """
    One OCR line resolved toward a canonical item.
    Attributes match the LineLike protocol consumed by core.fuzzy.
    """

    item: str | None          # canonical item name, or None when unresolved
    qty: int                  # parsed quantity (>=1)
    raw: str                  # original OCR line (stripped) — used for logging + fallback compare
    name_confidence: float    # 1.0 exact, ratio in [threshold,1) fuzzy, 0.0 unresolved
    matched: bool             # True when item is not None
    miss_reason: str = ""     # why it failed to resolve: "" | "unknown_item" | "no_item_text"
    qty_parse_failed: bool = False  # an x-token was present but could not be parsed

    def as_display(self) -> str:
        """`[Item] xN` rendering used for the OCR strip log."""
        if self.item is None:
            return ""
        return f"[{self.item}] x{self.qty}"

    def as_missed(self) -> str:
        """`{original OCR text} -> MISSED` rendering for the error / live log.

        Preserves the raw OCR text exactly as it was read (it already carries the
        quantity token), so missed input is fully traceable.
        """
        return f"{self.raw} -> MISSED"


def normalize_line(raw: str, fuzzy_threshold: float = FUZZY_NAME_THRESHOLD) -> NormalizedLine:
    """Normalize a single raw OCR line into a :class:`NormalizedLine`."""
    raw = raw.strip()

    # 1. Exact path: reuse the established substring matcher (confidence 1.0).
    exact = _parse_single_line(raw)
    if exact is not None:
        name, qty = exact
        return NormalizedLine(item=name, qty=qty, raw=raw, name_confidence=1.0, matched=True)

    # 2. Fuzzy path: split the cleaned line into a name candidate + quantity.
    cleaned = _clean_line(raw)
    m = _QTY_RE.search(cleaned)
    qty_parse_failed = False
    if m:
        name_text = cleaned[:m.start()].strip()
        present, qty_val = extract_quantity(cleaned[m.start():])
        if present and qty_val is None:
            qty_parse_failed = True
        qty = qty_val if (present and qty_val is not None) else 1
    else:
        name_text = cleaned.strip()
        qty = 1

    resolved = fuzzy_resolve_name(name_text, fuzzy_threshold) if name_text else None
    if resolved is not None:
        name, conf = resolved
        return NormalizedLine(item=name, qty=qty, raw=raw, name_confidence=conf,
                              matched=True, qty_parse_failed=qty_parse_failed)

    # 3. Unresolved: keep the line for alignment, but it can never commit.
    reason = "no_item_text" if not name_text else "unknown_item"
    return NormalizedLine(item=None, qty=qty, raw=raw, name_confidence=0.0,
                          matched=False, miss_reason=reason, qty_parse_failed=qty_parse_failed)


def normalize_frame(text: str, fuzzy_threshold: float = FUZZY_NAME_THRESHOLD) -> list[NormalizedLine]:
    """
    OCR text -> ordered (oldest first, newest last) list of normalized lines.
    Only bracketed lines are considered, matching the acquisition-log format.
    The list is unpadded: alignment works on suffix/prefix overlap, so empty
    padding is unnecessary.
    """
    out: list[NormalizedLine] = []
    for raw in text.splitlines():
        raw = raw.strip()
        # Require at least one bracket. Accept a line with only a closing ']' too:
        # the opening '[' is often fused with the first glyph and misread (e.g.
        # "[HAN ..." -> "THAN ..."), which would otherwise drop the whole line.
        if not raw or ("[" not in raw and "]" not in raw):
            continue
        out.append(normalize_line(raw, fuzzy_threshold))
    return out
