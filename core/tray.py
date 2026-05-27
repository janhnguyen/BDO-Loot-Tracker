import sys
from pathlib import Path

import pystray
from pystray import MenuItem as Item
from PIL import Image, ImageDraw

_RESOURCE_ROOT = (
    Path(sys._MEIPASS) if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[1]
)

def _load_icon() -> Image.Image:
    for candidate in (
        _RESOURCE_ROOT / "favicon.ico",
        _RESOURCE_ROOT / "ui" / "favicon.png",
    ):
        if candidate.exists():
            img = Image.open(candidate).convert("RGBA")
            return img.resize((64, 64), Image.LANCZOS)
    # fallback: plain drawn icon
    img = Image.new("RGB", (64, 64), "black")
    d = ImageDraw.Draw(img)
    d.rectangle((16, 16, 48, 48), fill="gold")
    return img

def run_tray(start, stop, set_zone, show_log) -> pystray.Icon:
    icon = pystray.Icon(
        "BDO Tracker",
        _load_icon(),
        menu=pystray.Menu(
            Item("Show", lambda: show_log()),
            Item("Start", lambda: start()),
            Item("Stop", lambda: stop()),
            Item("Quit", lambda: icon.stop()),
        ),
    )
    icon.run_detached()
    return icon
