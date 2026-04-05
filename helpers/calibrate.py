"""
calibrate_gui.py
────────────────────────────────────────────────────────────────
BDO Loot Tracker - Visual Calibration Tool

A fullscreen overlay that lets you drag a box over exactly the
loot notification area.

Usage:
    python calibrate.py                        # capture live screen
    python calibrate.py --image screenshot.png # load a saved image for debugging

Controls:
    • Click + drag  → draw the capture region
    • Drag edges/corners  → resize
    • Space / Enter  → confirm and run OCR test
    • R  → reset selection
    • Escape  → quit without saving
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import io
import os
import re
import sys
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox
from pathlib import Path
from PIL import Image, ImageTk, ImageEnhance, ImageFilter, ImageDraw, ImageFont
import mss

# ── Tesseract OCR ─────────────────────────────────────────────
try:
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

# ── Config ────────────────────────────────────────────────────
TRACKER_FILE = Path(__file__).resolve().parent.parent / ".env"

ACCENT      = "#D4A017"   # BDO gold
ACCENT_DIM  = "#9A7510"
RED         = "#E05050"
GREEN       = "#50C878"
BG_OVERLAY  = "#0D0B14"
TEXT_BRIGHT = "#F0EAD6"
TEXT_DIM    = "#7A7464"
EDGE_HIT    = 10          # px tolerance for edge/corner drag handles
MIN_SIZE    = 40          # minimum box dimension in px

# Debug image is written next to this script each time OCR is confirmed
DEBUG_IMAGE_PATH = Path(__file__).parent / "calibration_debug.png"

# ═════════════════════════════════════════════════════════════
class CalibrationApp:

    def __init__(self, source_image: Image.Image | None = None):
        self.root = tk.Tk()
        self.root.title("BDO Loot Tracker – Calibration")

        # ── acquire background image ──────────────────────────
        if source_image is not None:
            # --image mode: use the provided image as-is.
            # Treat its dimensions as the "screen" so percentages
            # are relative to the image, not the physical monitor.
            self.full_img = source_image.convert("RGB")
            self.screen_w, self.screen_h = self.full_img.size
        else:
            # Live mode: grab the primary monitor.
            with mss.mss() as sct:
                mon = sct.monitors[1]
                self.screen_w = mon["width"]
                self.screen_h = mon["height"]
                raw = sct.grab(mon)
                self.full_img = Image.frombytes(
                    "RGB", raw.size, raw.bgra, "raw", "BGRX"
                )

        # dim the screenshot so the selection stands out
        self.dim_img = ImageEnhance.Brightness(self.full_img).enhance(0.35)

        # ── window setup ──────────────────────────────────────
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG_OVERLAY)
        self.root.resizable(False, False)

        # canvas fills the screen
        self.canvas = tk.Canvas(
            self.root,
            width=self.screen_w,
            height=self.screen_h,
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)

        # draw dimmed background
        self._bg_tk = ImageTk.PhotoImage(self.dim_img)
        self.canvas.create_image(0, 0, anchor="nw", image=self._bg_tk)

        # ── selection state ───────────────────────────────────
        # current selection in screen pixels
        self.sel = {"x1": int(self.screen_w * 0.65),
                    "y1": int(self.screen_h * 0.72),
                    "x2": self.screen_w,
                    "y2": int(self.screen_h * 0.88)}
        self._drag_mode = None   # "new" | "move" | "n","s","e","w","ne",…
        self._drag_origin = (0, 0)
        self._sel_origin  = dict(self.sel)

        # canvas item ids
        self._preview_img_id = None
        self._overlay_ids    = []
        self._handle_ids     = []
        self._label_ids      = []

        # ── OCR result panel ──────────────────────────────────
        self._ocr_frame = tk.Frame(
            self.root, bg="#12101C",
            highlightbackground=ACCENT, highlightthickness=1,
        )
        self._ocr_title = tk.Label(
            self._ocr_frame, text="OCR PREVIEW",
            font=("Courier", 10, "bold"), fg=ACCENT, bg="#12101C",
            padx=12, pady=6,
        )
        self._ocr_title.pack(anchor="w")
        self._ocr_text = tk.Label(
            self._ocr_frame, text="",
            font=("Courier", 11), fg=TEXT_BRIGHT, bg="#12101C",
            justify="left", wraplength=420, padx=12, pady=0,
        )
        self._ocr_text.pack(anchor="w")
        self._ocr_hint = tk.Label(
            self._ocr_frame,
            text="",
            font=("Courier", 9), fg=TEXT_DIM, bg="#12101C",
            padx=12, pady=6,
        )
        self._ocr_hint.pack(anchor="w")

        # ── bindings ──────────────────────────────────────────
        self.canvas.bind("<ButtonPress-1>",   self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>",          self._on_hover)
        self.root.bind("<Return>",  lambda e: self._confirm())
        self.root.bind("<space>",   lambda e: self._confirm())
        self.root.bind("<r>",       lambda e: self._reset())
        self.root.bind("<Escape>",  lambda e: self._quit())

        # initial draw
        self._redraw()
        self._draw_instructions()

    # ─────────────────────────────────────────────────────────
    #  Selection geometry helpers
    # ─────────────────────────────────────────────────────────

    def _norm(self) -> tuple[int,int,int,int]:
        """Return (x1,y1,x2,y2) with x1<x2, y1<y2."""
        s = self.sel
        return (min(s["x1"],s["x2"]), min(s["y1"],s["y2"]),
                max(s["x1"],s["x2"]), max(s["y1"],s["y2"]))

    def _pcts(self) -> dict:
        x1,y1,x2,y2 = self._norm()
        W,H = self.screen_w, self.screen_h
        return dict(
            left   = round(x1/W, 4),
            top    = round(y1/H, 4),
            right  = round(x2/W, 4),
            bottom = round(y2/H, 4),
        )

    def _hit_zone(self, mx, my) -> str | None:
        """
        Returns which part of the selection the cursor is over:
        corner codes "nw","ne","sw","se", edge codes "n","s","e","w",
        "move" for interior, or None for outside.
        """
        x1,y1,x2,y2 = self._norm()
        in_x  = x1 <= mx <= x2
        in_y  = y1 <= my <= y2
        near_l = abs(mx - x1) <= EDGE_HIT
        near_r = abs(mx - x2) <= EDGE_HIT
        near_t = abs(my - y1) <= EDGE_HIT
        near_b = abs(my - y2) <= EDGE_HIT

        if not (in_x or near_l or near_r): return None
        if not (in_y or near_t or near_b): return None

        if near_t and near_l: return "nw"
        if near_t and near_r: return "ne"
        if near_b and near_l: return "sw"
        if near_b and near_r: return "se"
        if near_t: return "n"
        if near_b: return "s"
        if near_l: return "w"
        if near_r: return "e"
        if in_x and in_y: return "move"
        return None

    # ─────────────────────────────────────────────────────────
    #  Mouse events
    # ─────────────────────────────────────────────────────────

    def _on_hover(self, ev):
        zone = self._hit_zone(ev.x, ev.y)
        cursors = {
            "nw": "size_nw_se", "se": "size_nw_se",
            "ne": "size_ne_sw", "sw": "size_ne_sw",
            "n":  "size_ns",    "s":  "size_ns",
            "e":  "size_we",    "w":  "size_we",
            "move": "fleur",
        }
        self.canvas.configure(cursor=cursors.get(zone, "crosshair"))

    def _on_press(self, ev):
        zone = self._hit_zone(ev.x, ev.y)
        self._drag_origin = (ev.x, ev.y)
        self._sel_origin  = dict(self.sel)
        if zone in ("move", "n","s","e","w","nw","ne","sw","se"):
            self._drag_mode = zone
        else:
            # start a new selection
            self._drag_mode = "new"
            self.sel = {"x1": ev.x, "y1": ev.y, "x2": ev.x, "y2": ev.y}
        self._hide_ocr_panel()

    def _on_drag(self, ev):
        dx = ev.x - self._drag_origin[0]
        dy = ev.y - self._drag_origin[1]
        s  = self._sel_origin
        mode = self._drag_mode

        if mode == "new":
            self.sel["x2"] = ev.x
            self.sel["y2"] = ev.y
        elif mode == "move":
            w = s["x2"] - s["x1"]
            h = s["y2"] - s["y1"]
            nx1 = max(0, min(self.screen_w - w, s["x1"] + dx))
            ny1 = max(0, min(self.screen_h - h, s["y1"] + dy))
            self.sel = {"x1": nx1, "y1": ny1,
                        "x2": nx1 + w, "y2": ny1 + h}
        else:
            # edge / corner resize
            new = dict(s)
            if "n" in mode: new["y1"] = min(s["y2"] - MIN_SIZE, s["y1"] + dy)
            if "s" in mode: new["y2"] = max(s["y1"] + MIN_SIZE, s["y2"] + dy)
            if "w" in mode: new["x1"] = min(s["x2"] - MIN_SIZE, s["x1"] + dx)
            if "e" in mode: new["x2"] = max(s["x1"] + MIN_SIZE, s["x2"] + dx)
            self.sel = new

        self._redraw()

    def _on_release(self, _ev):
        self._drag_mode = None

    # ─────────────────────────────────────────────────────────
    #  Drawing
    # ─────────────────────────────────────────────────────────

    def _redraw(self):
        # remove old overlays
        for iid in self._overlay_ids + self._handle_ids + self._label_ids:
            self.canvas.delete(iid)
        self._overlay_ids  = []
        self._handle_ids   = []
        self._label_ids    = []
        if self._preview_img_id:
            self.canvas.delete(self._preview_img_id)
            self._preview_img_id = None

        x1,y1,x2,y2 = self._norm()
        W,H = self.screen_w, self.screen_h

        # ── bright preview inside selection ──────────────────
        crop = self.full_img.crop((x1, y1, x2, y2))
        self._preview_tk = ImageTk.PhotoImage(crop)
        self._preview_img_id = self.canvas.create_image(
            x1, y1, anchor="nw", image=self._preview_tk
        )

        # ── four dark quadrants outside selection ─────────────
        quads = [
            (0,   0,  W,  y1),   # top bar
            (0,  y2,  W,   H),   # bottom bar
            (0,  y1, x1,  y2),   # left strip
            (x2, y1,  W,  y2),   # right strip
        ]
        for qx1,qy1,qx2,qy2 in quads:
            if qx2 > qx1 and qy2 > qy1:
                iid = self.canvas.create_rectangle(
                    qx1, qy1, qx2, qy2,
                    fill="#0D0B14", stipple="gray50", outline=""
                )
                self._overlay_ids.append(iid)

        # ── selection border ──────────────────────────────────
        border = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline=ACCENT, width=2, fill=""
        )
        self._overlay_ids.append(border)

        # dashed inner border
        dashed = self.canvas.create_rectangle(
            x1+3, y1+3, x2-3, y2-3,
            outline=ACCENT_DIM, width=1, fill="", dash=(4,4)
        )
        self._overlay_ids.append(dashed)

        # ── corner + edge handles ─────────────────────────────
        cx, cy = (x1+x2)//2, (y1+y2)//2
        handle_pts = [
            (x1,y1),(x2,y1),(x1,y2),(x2,y2),  # corners
            (cx,y1),(cx,y2),(x1,cy),(x2,cy),   # edge midpoints
        ]
        for hx,hy in handle_pts:
            h = self.canvas.create_rectangle(
                hx-5, hy-5, hx+5, hy+5,
                fill=ACCENT, outline=BG_OVERLAY, width=1
            )
            self._handle_ids.append(h)

        # ── dimension label ───────────────────────────────────
        pw, ph = x2-x1, y2-y1
        p = self._pcts()
        dim_txt = (f"{pw}×{ph} px   "
                   f"L:{p['left']:.2f}  T:{p['top']:.2f}  "
                   f"R:{p['right']:.2f}  B:{p['bottom']:.2f}")

        # label background pill
        tw = len(dim_txt) * 7 + 16
        lx = max(4, min(W - tw - 4, x1))
        ly = max(4, y1 - 26)
        pill = self.canvas.create_rectangle(
            lx-4, ly-2, lx+tw, ly+16,
            fill="#12101C", outline=ACCENT_DIM, width=1
        )
        label = self.canvas.create_text(
            lx+4, ly+7,
            text=dim_txt, anchor="w",
            fill=ACCENT, font=("Courier", 9)
        )
        self._label_ids += [pill, label]

        # ── hint bar at bottom ────────────────────────────────
        hint_bg = self.canvas.create_rectangle(
            0, H-36, W, H,
            fill="#12101C", outline=""
        )
        hint = self.canvas.create_text(
            W//2, H-18,
            text="Drag to adjust  ·  Enter / Space = Confirm & test OCR  ·  R = Reset  ·  Esc = Quit",
            fill=TEXT_DIM, font=("Courier", 10), anchor="center"
        )
        self._label_ids += [hint_bg, hint]

    def _draw_instructions(self):
        """One-time heading drawn on startup."""
        W = self.screen_w
        self.canvas.create_rectangle(0, 0, W, 50, fill="#12101C", outline="")
        self.canvas.create_text(
            W//2, 25,
            text="BDO LOOT TRACKER  ·  CAPTURE REGION CALIBRATION",
            fill=ACCENT, font=("Courier", 13, "bold"), anchor="center"
        )

    # ─────────────────────────────────────────────────────────
    #  OCR panel
    # ─────────────────────────────────────────────────────────

    def _hide_ocr_panel(self):
        self._ocr_frame.place_forget()

    def _show_ocr_result(self, text: str, found_loot: bool):
        x1,y1,x2,y2 = self._norm()
        W,H = self.screen_w, self.screen_h

        self._ocr_text.config(
            text=text.strip() or "(no text detected)",
            fg=GREEN if found_loot else TEXT_BRIGHT,
        )
        hint = "✓ Loot pattern detected!" if found_loot else "No loot pattern found – reposition if needed"
        self._ocr_hint.config(
            text=hint + f"\nDebug image saved → calibration_debug.png"
                        f"\n\nEnter = Save & close   ·   R = Re-draw box",
            fg=GREEN if found_loot else ACCENT,
        )

        # position panel below (or above) the selection
        panel_w = 460
        px = max(0, min(W - panel_w, x1))
        if y2 + 160 < H:
            py = y2 + 12
        else:
            py = max(60, y1 - 160)

        self._ocr_frame.place(x=px, y=py, width=panel_w)
        self._ocr_frame.lift()

    # ─────────────────────────────────────────────────────────
    #  Actions
    # ─────────────────────────────────────────────────────────

    def _save_debug_image(self, raw_img: Image.Image, proc_img: Image.Image,
                          ocr_text: str, found_loot: bool):
        """
        Save an annotated debug PNG with:
          - Left panel:  raw 2× crop (what the camera sees)
          - Right panel: preprocessed B&W image (what Tesseract sees)
          - Info bar:    region percentages + pixel coords
          - OCR block:   full Tesseract output
        """
        p = self._pcts()
        x1, y1, x2, y2 = self._norm()

        # both panels share the same size (raw_img is already 2×)
        sw, sh = raw_img.size
        proc_rgb = proc_img.convert("RGB")

        BORDER    = 4
        GAP       = 8          # gap between the two panels
        BAR_H     = 36
        PADDING   = 12
        LINE_H    = 18
        FONT_SIZE = 14

        try:
            _font = ImageFont.truetype("cour.ttf", FONT_SIZE)
        except OSError:
            try:
                _font = ImageFont.truetype("DejaVuSansMono.ttf", FONT_SIZE)
            except OSError:
                _font = ImageFont.load_default()

        ocr_lines    = (ocr_text.strip() or "(no text detected)").splitlines()
        text_block_h = PADDING + (len(ocr_lines) + 1) * LINE_H + PADDING

        total_w = BORDER + sw + GAP + sw + BORDER
        total_h = BORDER + sh + BORDER + BAR_H + text_block_h

        debug = Image.new("RGB", (total_w, total_h), "#0D0B14")
        draw  = ImageDraw.Draw(debug)

        border_col = "#50C878" if found_loot else "#D4A017"

        # ── left panel: raw crop ──────────────────────────────
        draw.rectangle([0, 0, BORDER + sw + GAP//2 - 1, BORDER + sh + BORDER - 1],
                       outline=border_col, width=BORDER)
        debug.paste(raw_img, (BORDER, BORDER))

        # label
        draw.text((BORDER + 4, BORDER + 4), "RAW", font=_font, fill=border_col)

        # ── right panel: preprocessed ─────────────────────────
        rx = BORDER + sw + GAP
        draw.rectangle([rx - GAP//2, 0, total_w - 1, BORDER + sh + BORDER - 1],
                       outline="#5599FF", width=BORDER)
        debug.paste(proc_rgb, (rx, BORDER))
        draw.text((rx + 4, BORDER + 4), "TESSERACT INPUT", font=_font, fill="#5599FF")

        # ── info bar ──────────────────────────────────────────
        bar_y = BORDER + sh + BORDER
        draw.rectangle([0, bar_y, total_w - 1, bar_y + BAR_H - 1], fill="#12101C")
        info = (f"  L:{p['left']:.4f}  T:{p['top']:.4f}  "
                f"R:{p['right']:.4f}  B:{p['bottom']:.4f}"
                f"   |   {x2-x1}×{y2-y1} px  @  ({x1},{y1})")
        draw.text((PADDING, bar_y + (BAR_H - FONT_SIZE) // 2),
                  info, font=_font, fill="#D4A017")

        # ── OCR text block ────────────────────────────────────
        text_y = bar_y + BAR_H
        draw.rectangle([0, text_y, total_w - 1, total_h - 1], fill="#0D0B14")
        header_col = "#50C878" if found_loot else "#D4A017"
        header_txt = "OCR OUTPUT"
        draw.text((PADDING, text_y + PADDING // 2),
                  header_txt, font=_font, fill=header_col)
        for i, line in enumerate(ocr_lines):
            draw.text((PADDING, text_y + PADDING + (i + 1) * LINE_H),
                      line, font=_font, fill="#F0EAD6")

        debug.save(DEBUG_IMAGE_PATH, format="PNG")
        print(f"[calibrate] Debug image saved → {DEBUG_IMAGE_PATH}")

    def _reset(self):
        self._hide_ocr_panel()
        self.sel = {"x1": int(self.screen_w * 0.65),
                    "y1": int(self.screen_h * 0.72),
                    "x2": self.screen_w,
                    "y2": int(self.screen_h * 0.88)}
        self._redraw()

    def _confirm(self):
        """Run OCR on current selection and show result."""
        x1,y1,x2,y2 = self._norm()
        crop = self.full_img.crop((x1, y1, x2, y2))
        scaled = crop.resize((crop.width*2, crop.height*2), Image.LANCZOS)
        preprocessed = preprocess_for_ocr(scaled)

        if HAS_OCR:
            try:
                text = pytesseract.image_to_string(preprocessed, config="--psm 6")
            except Exception as exc:
                text = f"(OCR error: {exc})"
        else:
            text = "(pytesseract not installed – run: pip install pytesseract)"

        # check for loot patterns
        LOOT_RE = [
            re.compile(r"(?:You obtained:?\s+)(.+?)\s+[xX×]\s*(\d+)", re.I),
            re.compile(r"\[Loot\]\s+(.+?)\s+[xX×]\s*(\d+)", re.I),
        ]
        found = any(p.search(text) for p in LOOT_RE)

        self._save_debug_image(scaled, preprocessed, text, found)
        self._show_ocr_result(text, found)

        # bind Enter again to save after seeing result
        self.root.bind("<Return>", lambda e: self._save_and_close())
        self.root.bind("<space>",  lambda e: self._save_and_close())

    def _save_and_close(self):
        p = self._pcts()
        self._patch_tracker_file(p)
        self.root.destroy()

    def _quit(self):
        self.root.destroy()

    # ─────────────────────────────────────────────────────────
    #  Patch main.py in-place
    # ─────────────────────────────────────────────────────────

    def _patch_tracker_file(self, p: dict):
        replacements = {
            "REGION_LEFT_PCT":   p["left"],
            "REGION_TOP_PCT":    p["top"],
            "REGION_RIGHT_PCT":  p["right"],
            "REGION_BOTTOM_PCT": p["bottom"],
        }

        if not TRACKER_FILE.exists():
            messagebox.showinfo(
                "Saved (file not found)",
                f"Could not find .env next to this script.\n\n"
                f"Manually set these values in .env:\n\n"
                + "\n".join(f"{k}={v}" for k, v in replacements.items())
            )
            return

        src = TRACKER_FILE.read_text(encoding="utf-8")

        for var, val in replacements.items():
            if re.search(rf"^{re.escape(var)}=", src, flags=re.MULTILINE):
                src = re.sub(
                    rf"^({re.escape(var)}=).*",
                    rf"\g<1>{val}",
                    src,
                    flags=re.MULTILINE,
                )
            else:
                src = src.rstrip("\n") + f"\n{var}={val}\n"

        TRACKER_FILE.write_text(src, encoding="utf-8")
        print(f"[calibrate] Saved region to {TRACKER_FILE.name}:")
        for var, val in replacements.items():
            print(f"  {var}={val}")

    # ─────────────────────────────────────────────────────────

    def run(self):
        self.root.mainloop()


# ── OCR helper ───────────────────────────────────────────────

def preprocess_for_ocr(pil_img: Image.Image) -> Image.Image:
    """
    Isolate white text by requiring pixels to be both bright AND unsaturated
    (R ≈ G ≈ B).  Bright-but-coloured pixels (grass, path) are rejected.
    """
    from PIL import ImageOps, ImageFilter

    # Capture any text (white, orange, gold, yellow) against the dark
    # acquisition log background. Using peak channel instead of requiring
    # all channels to be bright, so coloured text isn't filtered out.
    BRIGHT_MIN = 135

    rgb  = pil_img.convert("RGB")
    data = rgb.load()
    w, h = rgb.size

    out = Image.new("L", (w, h), 255)   # start all white
    pix = out.load()

    for y in range(h):
        for x in range(w):
            r, g, b = data[x, y]
            if max(r, g, b) > BRIGHT_MIN:
                pix[x, y] = 0     # text → black (for Tesseract)

    # Light dilation to close gaps in thin letterforms
    out = out.filter(ImageFilter.MinFilter(3))
    return out


def _run_ocr(pil_img: Image.Image) -> str:
    """Pre-process then run Tesseract. PSM 6 = uniform block of text."""
    processed = preprocess_for_ocr(pil_img)
    return pytesseract.image_to_string(processed, config="--psm 6")


# ── Entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="BDO Loot Tracker - Visual Calibration Tool"
    )
    parser.add_argument(
        "--image", "-i",
        metavar="FILE",
        help="Path to a screenshot PNG/JPG to use instead of capturing the live screen.",
    )
    args = parser.parse_args()

    if args.image:
        img_path = Path(args.image)
        if not img_path.exists():
            print(f"[calibrate] ERROR: file not found: {img_path}")
            sys.exit(1)
        print(f"[calibrate] Loading image: {img_path}")
        source = Image.open(img_path)
        app = CalibrationApp(source_image=source)
    else:
        app = CalibrationApp()

    app.run()
