"""
Staging layer: Observed Loot -> Pending Buffer -> Confirmed Loot Event.

A newly-aligned line is never committed on first sight. Instead each visible log
line is modelled as a slot that accumulates sightings as it scrolls
upward through the window. A slot is committed exactly once, after it has been
seen in min_sightings consecutive frames, and its final item/quantity are
chosen by majority vote over every sighting gathered so far.

Because the log holds ~15-30 lines and capture runs ~10x/sec, a real drop is
re-observed many times before it scrolls away, so confirmation costs only a frame
or two of latency while making the final tally robust to per-frame OCR mistakes.

Slot bookkeeping is driven by core.alignment.AlignmentResult:
overlap carried-over slots become the new top of the window (and gain a fresh
corroborating sighting), and one new slot is appended per genuinely-new line.
"""

from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field
from .fuzzy import LineLike

@dataclass
class CommittedEvent:
    item: str          # canonical item name (voted)
    qty: int           # quantity (voted)
    confidence: float  # mean name confidence of the winning sightings
    sightings: int     # how many observations backed the decision

@dataclass
class Slot:
    """One physical log line tracked across frames via its sightings."""

    sightings: list = field(default_factory=list)  # list[LineLike]
    committed: bool = False

    @property
    def count(self) -> int:
        return len(self.sightings)

    def add(self, line: LineLike) -> None:
        self.sightings.append(line)

    def resolved(self) -> bool:
        """True if any sighting resolved to a known item."""
        return any(s.item is not None for s in self.sightings)

    def best_raw(self) -> str:
        """Most representative raw OCR text for logging this slot.

        Prefers the highest-confidence resolved sighting, else the first.
        """
        if not self.sightings:
            return ""
        named = [s for s in self.sightings if s.item is not None]
        pool = named or self.sightings
        return max(pool, key=lambda s: s.name_confidence).raw

    def vote(self) -> CommittedEvent | None:
        """
        Majority-vote the slot's sightings into a committed event.
        Returns None when no sighting ever resolved to a known item.
        """
        named = [s for s in self.sightings if s.item is not None]
        if not named:
            return None

        item = Counter(s.item for s in named).most_common(1)[0][0]
        relevant = [s for s in named if s.item == item]

        qty_counts = Counter(s.qty for s in relevant)
        top_count = qty_counts.most_common(1)[0][1]
        tied = [q for q, c in qty_counts.items() if c == top_count]
        if len(tied) == 1:
            qty = tied[0]
        else:
            # Unbiased tie-break: prefer the reading with the most summed name
            # confidence, then the value nearest the mean of all sightings, then
            # the smaller qty. (Deliberately not "larger qty", which would
            # systematically inflate totals under symmetric digit noise.)
            mean_qty = sum(s.qty for s in relevant) / len(relevant)
            qty = min(
                tied,
                key=lambda q: (
                    -sum(s.name_confidence for s in relevant if s.qty == q),
                    abs(q - mean_qty),
                    q,
                ),
            )

        confidence = sum(s.name_confidence for s in relevant) / len(relevant)
        return CommittedEvent(item=item, qty=qty, confidence=confidence, sightings=len(self.sightings))


class LootStager:
    """Turns aligned frames into confirmed loot events via multi-frame voting."""

    def __init__(self, min_sightings: int = 2):
        self._min_sightings = max(1, min_sightings)
        self._slots: list[Slot] = []
        self._dropped_unconfirmed = 0  # slots that scrolled off before commit (total)
        self._lost_unconfirmed = 0     # ... of those, ones that HAD resolved to an item
        self._missed_finalized = 0     # slots that hit the threshold but voted None
        # (best_raw, was_resolved) for slots dropped since the last drain — lets the
        # tracker surface every line that never became a confirmed event.
        self._dropped_records: list[tuple[str, bool]] = []

    def reset(self) -> None:
        self._slots = []
        self._dropped_unconfirmed = 0
        self._lost_unconfirmed = 0
        self._missed_finalized = 0
        self._dropped_records = []

    def seed(self, lines: list) -> None:
        """Establish the startup baseline.

        Marks every currently-visible line as already committed so loot that was
        on screen before tracking began is treated as history and never counted.
        Genuinely new lines that appear afterward are tracked normally.
        """
        self._slots = [Slot(sightings=[line], committed=True) for line in lines]

    @property
    def pending_count(self) -> int:
        return sum(1 for s in self._slots if not s.committed)

    @property
    def committed_count(self) -> int:
        return sum(1 for s in self._slots if s.committed)

    @property
    def dropped_unconfirmed(self) -> int:
        return self._dropped_unconfirmed

    @property
    def lost_unconfirmed(self) -> int:
        return self._lost_unconfirmed

    @property
    def missed_finalized(self) -> int:
        return self._missed_finalized

    def drain_dropped(self) -> list[tuple[str, bool]]:
        """Return and clear the (raw, was_resolved) records of slots that scrolled
        off uncommitted since the last call (for MISSED/LOST logging)."""
        records, self._dropped_records = self._dropped_records, []
        return records

    def observe(self, overlap: int, current_lines: list) -> list[CommittedEvent]:
        """Reconcile slots with the current frame and return newly-confirmed events.

        ``overlap`` is :attr:`AlignmentResult.overlap`; ``current_lines`` is the
        current frame's normalized lines (oldest first). Returns the events that
        crossed the confirmation threshold on *this* frame.
        """
        k = min(overlap, len(self._slots), len(current_lines))

        # Slots above the overlap scrolled off the top; record any uncommitted ones
        # so the tracker can report them (resolved = loot we saw but couldn't
        # confirm; unresolved = unparseable OCR that never became an event).
        for slot in self._slots[: len(self._slots) - k]:
            if not slot.committed:
                self._dropped_unconfirmed += 1
                was_resolved = slot.resolved()
                if was_resolved:
                    self._lost_unconfirmed += 1
                self._dropped_records.append((slot.best_raw(), was_resolved))

        carried = self._slots[len(self._slots) - k:] if k else []
        # Carried-over slots gain a corroborating sighting from the current frame.
        for slot, line in zip(carried, current_lines[:k]):
            slot.add(line)

        new_slots = [Slot(sightings=[line]) for line in current_lines[k:]]
        self._slots = carried + new_slots

        committed: list[CommittedEvent] = []
        for slot in self._slots:
            if not slot.committed and slot.count >= self._min_sightings:
                event = slot.vote()
                slot.committed = True  # mark regardless, so an unknown slot isn't re-checked forever
                if event is not None:
                    committed.append(event)
                else:
                    # Confirmed as persistent, but never resolved to a known item.
                    self._missed_finalized += 1
                    self._dropped_records.append((slot.best_raw(), False))
        return committed

    def flush(self) -> list[CommittedEvent]:
        """Commit every still-pending slot (e.g. on pause/stop) so trailing real
        loot isn't lost. Each slot still commits at most once."""
        committed: list[CommittedEvent] = []
        for slot in self._slots:
            if not slot.committed:
                event = slot.vote()
                slot.committed = True
                if event is not None:
                    committed.append(event)
        return committed
