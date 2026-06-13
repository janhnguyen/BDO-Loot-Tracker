"""
Fuzzy suffix-prefix frame alignment

Invariant : lines shared between two consecutive frames appear
as a suffix of the previous frame and a prefix of the current frame, because
the acquisition log is a FIFO that scrolls upward. So the genuinely new lines are
current[overlap:] for the largest valid overlap.

This generalises the reference diff_frames in three ways:
  - Fuzzy - overlap validity uses core.fuzzy.line_similarity with a
    per-pair floor instead of exact string equality, so a misread digit or a
    noisy character in a carried-over line doesn't break alignment.
  - Confidence - the mean per-pair similarity of the chosen overlap is
    returned alongside it.
  - Validation hook - an optional expected_new hint (from pixel-based
    scroll detection) disambiguates the otherwise-ambiguous case of many
    identical lines, where several overlaps are textually valid. Disagreement
    between text and pixels is recorded in diagnostics rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .fuzzy import LineLike, MatchConfig, line_similarity


@dataclass
class AlignmentResult:
    overlap: int                       # number of shared lines (k)
    new_lines: list                    # current[overlap:] — the genuinely new lines
    confidence: float                  # mean per-pair similarity over the overlap (0.0 when overlap==0)
    matched: int                       # corroborated pairs (== overlap)
    zero_overlap: bool                 # True only when both frames non-empty yet share nothing
    diagnostics: dict = field(default_factory=dict)


def _overlap_score(
    previous: Sequence[LineLike],
    current: Sequence[LineLike],
    k: int,
    cfg: MatchConfig,
) -> float | None:
    """
    Mean similarity if all k aligned pairs clear the floor, else None.
    Pairs for overlap k: previous[Lp-k+j] vs current[j] for j in [0, k).
    """
    if k == 0:
        return 1.0  # vacuously valid; callers treat k==0 specially
    lp = len(previous)
    total = 0.0
    for j in range(k):
        sim = line_similarity(previous[lp - k + j], current[j], cfg)
        if sim < cfg.line_accept:
            return None
        total += sim
    return total / k


def align(
    previous: Sequence[LineLike],
    current: Sequence[LineLike],
    cfg: MatchConfig = MatchConfig(),
    expected_new: int | None = None,
) -> AlignmentResult:
    """
    Align two normalized frames and return the newly-detected lines.
    expected_new: the number of new lines predicted by an
    independent signal (pixel scroll). When provided, the chosen overlap is the
    valid overlap closest to len(current) - expected_new; otherwise the
    largest valid overlap is chosen (the standard suffix-prefix rule).
    """
    lp, lc = len(previous), len(current)
    max_k = min(lp, lc)

    # All textually-valid overlaps and their mean similarities (k=0 always valid).
    scores: dict[int, float] = {}
    for k in range(max_k, -1, -1):
        s = _overlap_score(previous, current, k, cfg)
        if s is not None:
            scores[k] = s

    positive_valid = [k for k in scores if k > 0]
    largest_valid = max(positive_valid) if positive_valid else 0

    diagnostics: dict = {
        "lp": lp,
        "lc": lc,
        "valid_ks": sorted(scores.keys(), reverse=True),
        "largest_valid": largest_valid,
        "expected_new": expected_new,
        "target_k": None,
        "disagreement": False,
    }

    if expected_new is not None:
        target_k = max(0, lc - expected_new)
        diagnostics["target_k"] = target_k
        # Nearest valid overlap to the scroll prediction; ties prefer larger k.
        chosen = min(scores.keys(), key=lambda k: (abs(k - target_k), -k))
        diagnostics["disagreement"] = chosen != largest_valid
    else:
        chosen = largest_valid

    confidence = scores[chosen] if chosen > 0 else 0.0
    zero_overlap = chosen == 0 and lp > 0 and lc > 0
    if zero_overlap:
        diagnostics["reason"] = (
            "no suffix/prefix overlap cleared the similarity floor "
            f"(line_accept={cfg.line_accept}); treating all {lc} lines as new"
        )

    return AlignmentResult(
        overlap=chosen,
        new_lines=list(current[chosen:]),
        confidence=confidence,
        matched=chosen,
        zero_overlap=zero_overlap,
        diagnostics=diagnostics,
    )


# Glitch-frame guard

GLITCH_MAX_SKIPS = 3      # consecutive zero-overlap frames to skip before giving in
GLITCH_MIN_BASELINE = 3   # only guard when the previous frame had a real window


def is_glitch_frame(
    result: AlignmentResult,
    prev_len: int,
    consecutive_skips: int,
    max_skips: int = GLITCH_MAX_SKIPS,
    min_baseline: int = GLITCH_MIN_BASELINE,
) -> bool:
    """
    True if a populated frame abruptly lost all overlap.
    A single phantom or badly-garbled OCR line shifts every row and can collapse
    the suffix/prefix overlap to zero, which would otherwise discard the whole
    visible window's identity and re-count it. Such a frame is almost certainly a
    transient OCR glitch rather than a genuine full-window scroll, so the caller
    should skip it and realign against the same baseline next frame - but only
    up to max_skips in a row, so a real wholesale change eventually takes.
    """
    return (
        result.zero_overlap
        and prev_len >= min_baseline
        and consecutive_skips < max_skips
    )

# Implausibly large jumps cannot happen between two ~100-200ms captures: at most a
# handful of new loot lines appear. A much larger "new" count means the overlap
# was mis-estimated (the classic wall-of-identical-lines ambiguity), which is how
# duplicates get re-emitted. Skip such a frame unless pixel scroll confirms it.
PLAUSIBLE_MAX_NEW = 10

def is_implausible_jump(
    result: AlignmentResult,
    consecutive_skips: int,
    expected_new: int | None = None,
    max_new: int = PLAUSIBLE_MAX_NEW,
    max_skips: int = GLITCH_MAX_SKIPS,
) -> bool:
    """
    True if a frame claims far more new lines than is physically plausible.
    Corroboration by expected_new (pixel scroll) overrides the cap.
    Bounded by max_skips so a genuine wholesale
    change is eventually taken rather than skipped forever.
    """
    new = len(result.new_lines)
    if new <= max_new or consecutive_skips >= max_skips:
        return False
    if expected_new is not None and new <= expected_new + 1:
        return False  # pixel scroll confirms the jump
    return True
