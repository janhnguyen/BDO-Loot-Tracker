import os
import sys
from pathlib import Path
from typing import Union
from dotenv import load_dotenv

# When running as a PyInstaller bundle, data files live next to the .exe.
# In normal Python, they live next to main.py.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
ENV_PATH = BASE_DIR / ".env"

CHARACTER_NAME = os.getenv("CHARACTER_NAME", "MyCharacter")
DEFAULT_ZONE   = os.getenv("DEFAULT_ZONE", "Unknown")

# 1/POLL_INTERVAL = screenshots per second
POLL_INTERVAL = 0.1
OCR_UPSCALE = max(1.0, min(4.0, float(os.getenv("OCR_UPSCALE", "2.0"))))
SESSION_RESET_DELAY_SECONDS = float(os.getenv("SESSION_RESET_DELAY_SECONDS", "1.5"))
TRACKING_WINDOW_SIZE = int(os.getenv("TRACKING_WINDOW_SIZE", "20"))

# Alignment / staging pipeline tuning
# Frames a loot line must be observed before it is committed (multi-frame voting).
# 3 gives a 2-of-3 majority that overrides any single-frame OCR digit error while
# still confirming within ~0.3s at the default poll rate.
LOOT_MIN_SIGHTINGS = max(1, int(os.getenv("LOOT_MIN_SIGHTINGS", "3")))
# Fuzzy name-resolution acceptance (difflib ratio) for canonicalising OCR names.
NAME_FUZZY_THRESHOLD = float(os.getenv("NAME_FUZZY_THRESHOLD", "0.82"))
# Stability gate: skip OCR until the region holds still. diff is mean abs pixel
# change (0-255) on a downscaled grayscale frame.
ENABLE_STABILITY_GATE = os.getenv("ENABLE_STABILITY_GATE", "true").strip().lower() in {"1", "true", "yes", "on"}
STABILITY_DIFF_THRESHOLD = float(os.getenv("STABILITY_DIFF_THRESHOLD", "3.0"))
STABILITY_MIN_FRAMES = max(1, int(os.getenv("STABILITY_MIN_FRAMES", "2")))
# Pixel scroll detection: advisory hint that disambiguates many-identical-lines.
ENABLE_SCROLL_HINT = os.getenv("ENABLE_SCROLL_HINT", "true").strip().lower() in {"1", "true", "yes", "on"}
# Anti-duplicate guard: max new loot lines plausibly appearing between two frames.
# A larger "new" count (unconfirmed by pixel scroll) is treated as a misalignment
# and skipped, preventing the wall-of-identical-lines re-emission bug.
MAX_PLAUSIBLE_NEW = max(1, int(os.getenv("MAX_PLAUSIBLE_NEW", "10")))
# How often the tracker logs a [METRICS] pipeline summary (seconds).
METRICS_LOG_INTERVAL_SECONDS = float(os.getenv("METRICS_LOG_INTERVAL_SECONDS", "30"))

REGION_LEFT_PCT   = float(os.getenv("REGION_LEFT_PCT",   "0.65"))
REGION_TOP_PCT    = float(os.getenv("REGION_TOP_PCT",    "0.72"))
REGION_RIGHT_PCT  = float(os.getenv("REGION_RIGHT_PCT",  "1.0"))
REGION_BOTTOM_PCT = float(os.getenv("REGION_BOTTOM_PCT", "0.88"))

LOCAL_DB_PATH = Path(os.getenv("LOCAL_DB_PATH", str(BASE_DIR / "data" / "loot_tracker.db")))

def _get_bool_env(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).strip().lower() in {"1", "true", "yes", "on"}

SHOW_OCR_LOG = _get_bool_env("SHOW_OCR_LOG", False)
SHOW_OCR_PANE = _get_bool_env("SHOW_OCR_PANE", False)
SHOW_LIVE_LOG = _get_bool_env("SHOW_LIVE_LOG", False)
SHOW_SYSTEM_MESSAGES = _get_bool_env("SHOW_SYSTEM_MESSAGES", True)
ITEMS_FONT_SIZE = max(12, min(20, int(os.getenv("ITEMS_FONT_SIZE", "12"))))

KEYBIND_START = os.getenv("KEYBIND_START", "Control+Shift+A")
KEYBIND_PAUSE = os.getenv("KEYBIND_PAUSE", "Control+Shift+S")
KEYBIND_STOP  = os.getenv("KEYBIND_STOP",  "Control+Shift+D")

WINDOW_WIDTH  = max(520, int(os.getenv("WINDOW_WIDTH",  "520")))
WINDOW_HEIGHT = max(400, int(os.getenv("WINDOW_HEIGHT", "760")))

def save_env_setting(key: str, value: Union[str, bool, int, float]) -> None:
    serialized_value = str(value).lower() if isinstance(value, bool) else str(value)
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    updated = False
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{key}={serialized_value}"
            updated = True
            break

    if not updated:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={serialized_value}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = serialized_value