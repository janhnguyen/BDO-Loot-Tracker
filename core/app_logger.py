from __future__ import annotations

import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

_log_dir: Path | None = None
_version: str = "0.0.0"


def _header(log_dir: Path, version: str) -> list[str]:
    return [
        "=== BDO Loot Tracker ===",
        f"Version:  {version}",
        f"Python:   {sys.version}",
        f"Platform: {platform.platform()}",
        f"Frozen:   {getattr(sys, 'frozen', False)}",
        f"Log dir:  {log_dir}",
        "",
    ]


def _safe_filename(name: str) -> str:
    """Replace characters invalid in Windows filenames."""
    invalid = r'\/:*?"<>|'
    result = "".join(c if c not in invalid else "_" for c in name)
    return result.strip("_ ") or "Unknown"


def _write_error_log(exc_type, exc_value, exc_tb) -> None:
    if _log_dir is None:
        return
    _log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    filename = f"Error_{now.strftime('%Y-%m-%d_%H-%M-%S')}.log"
    lines = _header(_log_dir, _version)
    lines.append(f"Error time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.extend(traceback.format_exception(exc_type, exc_value, exc_tb))
    (_log_dir / filename).write_text("\n".join(lines), encoding="utf-8")


def setup_error_logger(log_dir: Path, version: str) -> None:
    """Call once at startup to enable Error_YYYY-MM-DD_HH-MM-SS.log on any unhandled exception."""
    global _log_dir, _version
    _log_dir = log_dir
    _version = version
    log_dir.mkdir(parents=True, exist_ok=True)

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _write_error_log(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook


def log_caught_exception() -> None:
    """Write an Error_YYYY-MM-DD_HH-MM-SS.log for the current exception (call from an except block)."""
    _write_error_log(*sys.exc_info())


def log_missed(line: str) -> None:
    """
    Append a missed/lost OCR entry to a rolling daily Missed_YYYY-MM-DD.log.
    line is the already-formatted record, e.g. "THAN Crystal of Ruin x1 -> MISSED".
    This makes every OCR input that never became a confirmed loot event searchable
    in the existing logs directory. Best-effort: never raises into the OCR loop.
    """
    if _log_dir is None:
        return
    try:
        _log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        filename = f"Missed_{now.strftime('%Y-%m-%d')}.log"
        with (_log_dir / filename).open("a", encoding="utf-8") as f:
            f.write(f"[{now.strftime('%H:%M:%S')}] {line}\n")
    except OSError:
        pass


class SessionLogger:
    """Accumulates per-line OCR data for one tracking session and writes a log on finalize()."""

    def __init__(self, log_dir: Path, zone: str, start_time: datetime, version: str):
        self._log_dir = log_dir
        self._zone = zone
        self._start_time = start_time
        self._version = version
        self._lines: list[tuple[str, str | None]] = []

    def add_ocr_lines(self, pairs: list[tuple[str, str | None]]) -> None:
        """Append (raw_line, cleaned_line_or_None) pairs from one OCR frame."""
        self._lines.extend(pairs)

    def finalize(self, final_zone: str) -> None:
        """Write ZONE_HH-MM-SS.log and close the session."""
        self._log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        zone_safe = _safe_filename(final_zone)
        filename = f"{zone_safe}_{self._start_time.strftime('%Y-%m-%d_%H-%M-%S')}.log"

        lines = _header(self._log_dir, self._version)
        lines.append(f"Session zone:  {final_zone}")
        lines.append(f"Session start: {self._start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Session end:   {now.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("--- OCR Lines (raw  ->  cleaned) ---")
        lines.append("")

        for raw, cleaned in self._lines:
            cleaned_str = cleaned if cleaned else "(no match)"
            lines.append(f"{raw}  ->  {cleaned_str}")

        (_log_dir / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
