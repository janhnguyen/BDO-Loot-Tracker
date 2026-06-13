"""
Per-frame diagnostics for debugging alignment and scroll detection.
Captures the signals that explain why a frame produced the new-line count it
did, so alignment disagreements and zero-overlap events can be surfaced.
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class FrameDiagnostics:
    frame_lines: int            # normalized lines in the current frame
    overlap: int                # chosen suffix/prefix overlap
    new_lines: int              # genuinely-new lines detected
    confidence: float           # alignment confidence (mean per-pair similarity)
    zero_overlap: bool          # both frames non-empty yet shared nothing
    scroll_px: int              # detected pixel scroll (advisory)
    scroll_confident: bool      # whether the scroll detector trusted its result
    expected_new: int | None    # new-line count predicted from scroll, if usable
    text_new: int               # new-line count from text alignment alone
    disagreement: bool          # text vs scroll predicted different counts
    pending: int                # slots awaiting confirmation
    committed_now: int          # events confirmed on this frame
    reason: str = ""            # human-readable note (zero-overlap / disagreement)

    def is_noteworthy(self) -> bool:
        """True when this frame is worth logging (something looked off)."""
        return self.zero_overlap or self.disagreement

    def summary(self) -> str:
        """One-line summary for the system log."""
        bits = [
            f"lines={self.frame_lines}",
            f"overlap={self.overlap}",
            f"new={self.new_lines}",
            f"conf={self.confidence:.2f}",
        ]
        if self.expected_new is not None:
            bits.append(f"scroll_new={self.expected_new}(text={self.text_new})")
        if self.scroll_px:
            bits.append(f"scroll_px={self.scroll_px}")
        if self.pending:
            bits.append(f"pending={self.pending}")
        if self.reason:
            bits.append(self.reason)
        return "[ALIGN] " + " ".join(bits)
