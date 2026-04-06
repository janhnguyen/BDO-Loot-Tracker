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

SUPABASE_URL   = os.getenv("SUPABASE_URL")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY")
CHARACTER_NAME = os.getenv("CHARACTER_NAME", "MyCharacter")
DEFAULT_ZONE   = os.getenv("DEFAULT_ZONE", "Unknown")

POLL_INTERVAL = 0
SESSION_RESET_DELAY_SECONDS = float(os.getenv("SESSION_RESET_DELAY_SECONDS", "1.5"))
TRACKING_WINDOW_SIZE = int(os.getenv("TRACKING_WINDOW_SIZE", "20"))

REGION_LEFT_PCT   = float(os.getenv("REGION_LEFT_PCT",   "0.65"))
REGION_TOP_PCT    = float(os.getenv("REGION_TOP_PCT",    "0.72"))
REGION_RIGHT_PCT  = float(os.getenv("REGION_RIGHT_PCT",  "1.0"))
REGION_BOTTOM_PCT = float(os.getenv("REGION_BOTTOM_PCT", "0.88"))

LOCAL_DB_PATH = Path(os.getenv("LOCAL_DB_PATH", str(BASE_DIR / "data" / "loot_tracker.db")))

def _get_bool_env(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).strip().lower() in {"1", "true", "yes", "on"}

SHOW_OCR_LOG = _get_bool_env("SHOW_OCR_LOG", False)
SHOW_OCR_PANE = _get_bool_env("SHOW_OCR_PANE", False)
ITEMS_FONT_SIZE = max(12, min(20, int(os.getenv("ITEMS_FONT_SIZE", "12"))))

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