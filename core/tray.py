import pystray
from pystray import MenuItem as Item
from PIL import Image, ImageDraw

def create_icon():
    img = Image.new("RGB", (64, 64), "black")
    d = ImageDraw.Draw(img)
    d.rectangle((16, 16, 48, 48), fill="gold")
    return img

def run_tray(start, stop, set_zone, show_log):
    icon = pystray.Icon(
        "BDO Tracker",
        create_icon(),
        menu=pystray.Menu(
            Item("Show", lambda: show_log()),
            Item("Start", lambda: start()),
            Item("Stop", lambda: stop()),
            Item("Quit", lambda: icon.stop()),
        ),
    )
    icon.run_detached()