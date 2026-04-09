from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# When frozen by PyInstaller, bundled resources live in sys._MEIPASS.
# In development they live relative to this source file.
_RESOURCE_ROOT = (
    Path(sys._MEIPASS) if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[1]
)
_CHANGELOG_PATH = _RESOURCE_ROOT / "CHANGELOG.md"

import webview


class LogWindow:
    """Native desktop UI host for the BDO loot tracker."""

    def __init__(
        self,
        master=None,
        get_status_cb=None,
        start_cb=None,
        stop_cb=None,
        list_sessions_cb=None,
        upload_session_cb=None,
        calibrate_cb=None,
        show_ocr_default: bool = False,
        ocr_settings_changed_cb=None,
        get_tracking_window_cb=None,
        set_tracking_window_cb=None,
        get_font_size_cb=None,
        set_font_size_cb=None,
        get_db_stats_cb=None,
        show_ocr_pane_default: bool = False,
        show_live_log_default: bool = True,
        ocr_pane_settings_changed_cb=None,
        live_log_settings_changed_cb=None,
        pause_cb=None,
        resume_cb=None,
        is_paused_cb=None,
    ):
        self.get_status_cb = get_status_cb
        self.start_cb = start_cb
        self.stop_cb = stop_cb
        self.list_sessions_cb = list_sessions_cb
        self.upload_session_cb = upload_session_cb
        self.calibrate_cb = calibrate_cb
        self.ocr_settings_changed_cb = ocr_settings_changed_cb
        self.get_tracking_window_cb = get_tracking_window_cb
        self.set_tracking_window_cb = set_tracking_window_cb
        self.get_font_size_cb = get_font_size_cb
        self.set_font_size_cb = set_font_size_cb
        self.get_db_stats_cb = get_db_stats_cb
        self.ocr_pane_settings_changed_cb = ocr_pane_settings_changed_cb
        self.live_log_settings_changed_cb = live_log_settings_changed_cb
        self.pause_cb = pause_cb
        self.resume_cb = resume_cb
        self.is_paused_cb = is_paused_cb

        self.show_ocr = show_ocr_default
        self.show_ocr_pane = show_ocr_pane_default
        self.show_live_log = show_live_log_default

        self._ocr_frame_raw: bytes | None = None
        self._ocr_frame_processed: bytes | None = None

        self._lock = threading.Lock()
        self._totals: dict[str, int] = {}
        self._logs: list[str] = []
        self._session_labels: dict[str, int] = {}
        self._selected_session = "No sessions"
        self._last_sessions_refresh = 0.0
        self._timer_started_at = None
        self._timer_elapsed_seconds = 0.0

        self._host = "127.0.0.1"
        self._port = 8765
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._window = None

    def add_event(self, event):
        ts = event.timestamp.strftime("%H:%M:%S")
        line = f"[{ts}] {event.item_name} ×{event.quantity}"
        with self._lock:
            self._logs.append(line)
            self._logs = self._logs[-400:]
            self._totals[event.item_name] = self._totals.get(event.item_name, 0) + event.quantity

    def add_raw_ocr(self, text):
        if not self.show_ocr and not self.show_ocr_pane:
            return
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        preview = " ↵ ".join(ln for ln in text.strip().splitlines() if ln.strip())
        if not preview:
            return
        with self._lock:
            self._logs.append(f"[{ts}] [OCR] {preview}")
            self._logs = self._logs[-400:]

    def add_ocr_frame(self, raw_img, processed_img):
        if not self.show_ocr_pane:
            return
        import io
        buf_raw = io.BytesIO()
        raw_img.save(buf_raw, format="PNG")
        buf_proc = io.BytesIO()
        processed_img.save(buf_proc, format="PNG")
        with self._lock:
            self._ocr_frame_raw = buf_raw.getvalue()
            self._ocr_frame_processed = buf_proc.getvalue()

    def _append_system(self, text: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        with self._lock:
            self._logs.append(f"[{ts}] [SYSTEM] {text}")
            self._logs = self._logs[-400:]

    def _clear_totals(self):
        with self._lock:
            self._totals = {}

    def clear_totals(self):
        self._clear_totals()

    def start_timer(self):
        with self._lock:
            self._timer_started_at = time.monotonic()
            self._timer_elapsed_seconds = 0.0

    def pause_timer(self):
        with self._lock:
            if self._timer_started_at is not None:
                self._timer_elapsed_seconds = max(
                    0.0, time.monotonic() - self._timer_started_at
                )
                self._timer_started_at = None

    def resume_timer(self):
        with self._lock:
            if self._timer_started_at is None:
                self._timer_started_at = time.monotonic() - self._timer_elapsed_seconds

    def stop_timer(self) -> float:
        with self._lock:
            if self._timer_started_at is not None:
                self._timer_elapsed_seconds = max(
                    0.0, time.monotonic() - self._timer_started_at
                )
            self._timer_started_at = None
            return self._timer_elapsed_seconds

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total_seconds = int(max(0.0, seconds))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def schedule_session_totals_reset(self, delay_seconds: float):
        timer = threading.Timer(max(0.0, delay_seconds), self._clear_totals)
        timer.daemon = True
        timer.start()

    def refresh_sessions(self):
        self._last_sessions_refresh = time.monotonic()
        if not self.list_sessions_cb:
            return
        sessions = self.list_sessions_cb()

        labels: list[str] = []
        session_labels: dict[str, int] = {}
        for session in sessions:
            status = "open" if session.ended_at is None else "closed"
            started = session.started_at
            ended = session.ended_at or "In progress"
            label = f"#{session.id} | {started} → {ended} | {status}"
            session_labels[label] = session.id
            labels.append(label)

        with self._lock:
            self._session_labels = session_labels
            if not labels:
                labels = ["No sessions"]
            if self._selected_session not in labels:
                self._selected_session = labels[0]

    def _upload_selected_session(self):
        if not self.upload_session_cb:
            return
        with self._lock:
            label = self._selected_session
            session_id = self._session_labels.get(label)
        if session_id is None:
            self._append_system("No session selected.")
            return
        message = self.upload_session_cb(session_id)
        self._append_system(message)
        self.refresh_sessions()

    def _persist_ocr_settings(self):
        if self.ocr_settings_changed_cb:
            self.ocr_settings_changed_cb(self.show_ocr)

    def _state(self) -> dict[str, Any]:
        if self.get_status_cb:
            running, zone = self.get_status_cb()
        else:
            running, zone = False, "Unknown"
        if time.monotonic() - self._last_sessions_refresh > 5:
            self.refresh_sessions()
        with self._lock:
            totals = sorted(self._totals.items(), key=lambda item: item[1], reverse=True)
            sessions = sorted(self._session_labels.keys(), reverse=True) or ["No sessions"]
            if self._timer_started_at is None:
                timer_seconds = self._timer_elapsed_seconds
            else:
                timer_seconds = max(0.0, time.monotonic() - self._timer_started_at)
            timer_display = self._format_duration(timer_seconds)
            return {
                "running": running,
                "paused": self.is_paused_cb() if self.is_paused_cb else False,
                "zone": zone,
                "timer": timer_display,
                "timer_seconds": timer_seconds,
                "logs": self._logs[-250:],
                "totals": [{"name": name, "qty": qty} for name, qty in totals],
                "show_ocr": self.show_ocr,
                "show_ocr_pane": self.show_ocr_pane,
                "show_live_log": self.show_live_log,
                "tracking_window_size": self.get_tracking_window_cb() if self.get_tracking_window_cb else 20,
                "items_font_size": self.get_font_size_cb() if self.get_font_size_cb else 12,
                "sessions": sessions,
                "selected_session": self._selected_session,
            }

    def _handle_action(self, action: str, body: dict[str, Any]):
        if action == "start" and self.start_cb:
            self.start_cb()
        elif action == "pause" and self.pause_cb:
            self.pause_cb()
        elif action == "resume" and self.resume_cb:
            self.resume_cb()
        elif action == "stop" and self.stop_cb:
            self.stop_cb()
        elif action == "calibrate" and self.calibrate_cb:
            message = self.calibrate_cb()
            if message:
                self._append_system(message)
        elif action == "upload":
            self._upload_selected_session()
        elif action == "select_session":
            value = str(body.get("value", "No sessions"))
            with self._lock:
                self._selected_session = value
        elif action == "toggle_ocr":
            self.show_ocr = bool(body.get("value", False))
            self._persist_ocr_settings()
        elif action == "toggle_ocr_pane":
            self.show_ocr_pane = bool(body.get("value", False))
            if self.ocr_pane_settings_changed_cb:
                self.ocr_pane_settings_changed_cb(self.show_ocr_pane)
        elif action == "toggle_live_log":
            self.show_live_log = bool(body.get("value", False))
            if self.live_log_settings_changed_cb:
                self.live_log_settings_changed_cb(self.show_live_log)
        elif action == "set_tracking_window" and self.set_tracking_window_cb:
            self.set_tracking_window_cb(body.get("value", 20))
        elif action == "set_font_size" and self.set_font_size_cb:
            self.set_font_size_cb(body.get("value", 12))
        elif action == "clear_totals":
            self._clear_totals()

    def _make_handler(self):
        log_window = self
        ui_root = _RESOURCE_ROOT / "ui" / "dist"

        class Handler(BaseHTTPRequestHandler):
            def _write_json(self, payload: dict[str, Any], status: int = 200):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/state":
                    self._write_json(log_window._state())
                    return

                if self.path == "/api/changelog":
                    text = _CHANGELOG_PATH.read_text(encoding="utf-8") if _CHANGELOG_PATH.exists() else ""
                    self._write_json({"text": text})
                    return

                if self.path.startswith("/api/ocr_frame"):
                    frame_type = "raw" if "type=raw" in self.path else "processed"
                    with log_window._lock:
                        data = log_window._ocr_frame_raw if frame_type == "raw" else log_window._ocr_frame_processed
                    if data:
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        self.wfile.write(data)
                    else:
                        self.send_error(HTTPStatus.NOT_FOUND)
                    return

                if self.path == "/api/db_stats":
                    stats = log_window.get_db_stats_cb() if log_window.get_db_stats_cb else {}
                    self._write_json(stats)
                    return

                target = self.path.split("?", 1)[0]
                if target in {"/", ""}:
                    target = "/index.html"
                file_path = (ui_root / target.lstrip("/")).resolve()
                if not str(file_path).startswith(str(ui_root)) or not file_path.exists():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return

                mime = "text/plain"
                suffix = file_path.suffix
                if suffix == ".html":
                    mime = "text/html"
                elif suffix == ".js":
                    mime = "application/javascript"
                elif suffix == ".css":
                    mime = "text/css"
                elif suffix == ".png":
                    mime = "image/png"
                elif suffix in {".jpg", ".jpeg"}:
                    mime = "image/jpeg"
                elif suffix == ".svg":
                    mime = "image/svg+xml"
                elif suffix == ".ico":
                    mime = "image/x-icon"

                data = file_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                if not self.path.startswith("/api/"):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                action = self.path.split("/api/", 1)[1]
                length = int(self.headers.get("Content-Length", "0"))
                payload = {}
                if length > 0:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                log_window._handle_action(action, payload)
                self._write_json({"ok": True})

            def log_message(self, format, *args):
                return

        return Handler

    def show(self):
        if self._window is None:
            return
        self._window.show()
        if hasattr(self._window, "restore"):
            self._window.restore()
        if hasattr(self._window, "bring_to_front"):
            self._window.bring_to_front()

    @staticmethod
    def _is_webview2_installed() -> bool:
        if sys.platform != "win32":
            return True
        import winreg
        keys = [
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        ]
        for key_path in keys:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    winreg.OpenKey(hive, key_path).Close()
                    return True
                except OSError:
                    continue
        return False

    def _ensure_webview2(self):
        """Silently install WebView2 if missing, using the bundled bootstrapper."""
        if self._is_webview2_installed():
            return
        bootstrapper = _RESOURCE_ROOT / "helpers" / "MicrosoftEdgeWebview2Setup.exe"
        if not bootstrapper.exists():
            return
        import subprocess
        subprocess.run([str(bootstrapper), "/silent", "/install"], check=False)

    def run(self):
        self.refresh_sessions()
        self._ensure_webview2()
        self._server = ThreadingHTTPServer((self._host, self._port), self._make_handler())
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        try:
            self._window = webview.create_window(
                "BDO Loot Tracker",
                f"http://{self._host}:{self._port}",
                width=1132,  # CSS max-width (1100) + horizontal padding (2×16)
                height=760,
                min_size=(520, 400),
            )
            webview.start()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            import ctypes
            if sys.platform == "win32":
                ctypes.windll.user32.MessageBoxW(
                    0,
                    (
                        "The app requires the Microsoft Edge WebView2 Runtime.\n\n"
                        "Please download and install it, then restart:\n"
                        "https://developer.microsoft.com/en-us/microsoft-edge/webview2/"
                    ),
                    "WebView2 Required",
                    0x10,  # MB_ICONERROR
                )
            else:
                print(f"Failed to start webview: {e}")
        finally:
            if self._server:
                self._server.shutdown()
                self._server.server_close()
