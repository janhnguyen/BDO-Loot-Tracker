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

from .parser import get_item_value_for_zone
from .config import save_env_setting

# When frozen by PyInstaller, bundled resources live in sys._MEIPASS.
# In development they live relative to this source file.
_RESOURCE_ROOT = (
    Path(sys._MEIPASS) if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[1]
)
_CHANGELOG_PATH = _RESOURCE_ROOT / "CHANGELOG.md"

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow


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
        get_session_detail_cb=None,
        delete_session_cb=None,
        show_ocr_pane_default: bool = False,
        ocr_pane_settings_changed_cb=None,
        pause_cb=None,
        resume_cb=None,
        is_paused_cb=None,
        update_market_prices_cb=None,
        show_live_log_default: bool = False,
        keybind_start_default: str = "Control+Shift+A",
        keybind_pause_default: str = "Control+Shift+S",
        keybind_stop_default: str = "Control+Shift+D",
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
        self.get_session_detail_cb = get_session_detail_cb
        self.delete_session_cb = delete_session_cb
        self.ocr_pane_settings_changed_cb = ocr_pane_settings_changed_cb
        self.pause_cb = pause_cb
        self.resume_cb = resume_cb
        self.is_paused_cb = is_paused_cb
        self.update_market_prices_cb = update_market_prices_cb
        self._market_updating = False

        self.show_live_log = show_live_log_default
        self._keybind_start = keybind_start_default
        self._keybind_pause = keybind_pause_default
        self._keybind_stop = keybind_stop_default

        self.show_ocr = show_ocr_default
        self.show_ocr_pane = show_ocr_pane_default

        self._ocr_frame_raw: bytes | None = None
        self._ocr_frame_processed: bytes | None = None

        self._lock = threading.Lock()
        self._totals: dict[str, int] = {}
        self._session_silver: float = 0.0
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
        value = get_item_value_for_zone(event.item_name, event.zone) * event.quantity
        with self._lock:
            self._logs.append(line)
            self._logs = self._logs[-400:]
            self._totals[event.item_name] = self._totals.get(event.item_name, 0) + event.quantity
            self._session_silver += value

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
            self._session_silver = 0.0

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
                "session_silver": self._session_silver,
                "show_ocr": self.show_ocr,
                "show_ocr_pane": self.show_ocr_pane,
                "tracking_window_size": self.get_tracking_window_cb() if self.get_tracking_window_cb else 20,
                "items_font_size": self.get_font_size_cb() if self.get_font_size_cb else 12,
                "sessions": sessions,
                "selected_session": self._selected_session,
                "market_updating": self._market_updating,
                "show_live_log": self.show_live_log,
                "keybind_start": self._keybind_start,
                "keybind_pause": self._keybind_pause,
                "keybind_stop": self._keybind_stop,
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
        elif action == "set_tracking_window" and self.set_tracking_window_cb:
            self.set_tracking_window_cb(body.get("value", 20))
        elif action == "set_font_size" and self.set_font_size_cb:
            self.set_font_size_cb(body.get("value", 12))
        elif action == "clear_totals":
            self._clear_totals()
        elif action == "toggle_live_log":
            self.show_live_log = bool(body.get("value", False))
            save_env_setting("SHOW_LIVE_LOG", self.show_live_log)
        elif action == "set_keybind":
            act = body.get("action", "")
            key = str(body.get("key", "")).strip()
            if act == "start" and key:
                self._keybind_start = key
                save_env_setting("KEYBIND_START", key)
            elif act == "pause" and key:
                self._keybind_pause = key
                save_env_setting("KEYBIND_PAUSE", key)
            elif act == "stop" and key:
                self._keybind_stop = key
                save_env_setting("KEYBIND_STOP", key)
        elif action == "update_market_prices" and self.update_market_prices_cb:
            if not self._market_updating:
                self._market_updating = True
                self.update_market_prices_cb()
        elif action == "delete_session" and self.delete_session_cb:
            session_id = body.get("session_id")
            if session_id is not None:
                self.delete_session_cb(int(session_id))

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

                if self.path.startswith("/api/session_detail"):
                    from urllib.parse import urlparse, parse_qs
                    params = parse_qs(urlparse(self.path).query)
                    try:
                        session_id = int(params.get("id", ["0"])[0])
                    except (ValueError, IndexError):
                        session_id = 0
                    detail = (
                        log_window.get_session_detail_cb(session_id)
                        if log_window.get_session_detail_cb
                        else {}
                    )
                    self._write_json(detail)
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
        # QTimer.singleShot is thread-safe — queues the call on the main event loop
        QTimer.singleShot(0, self._bring_to_front)

    def _bring_to_front(self):
        if self._window:
            self._window.showNormal()
            self._window.raise_()
            self._window.activateWindow()

    def run(self):
        self.refresh_sessions()
        self._server = ThreadingHTTPServer((self._host, self._port), self._make_handler())
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        try:
            import os
            os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--log-level=3")
            app = QApplication.instance() or QApplication(sys.argv)
            self._window = QMainWindow()
            self._window.setWindowTitle("BDO Loot Tracker")
            self._window.resize(520, 760)
            self._window.setMinimumSize(520, 400)
            view = QWebEngineView()
            view.load(QUrl(f"http://{self._host}:{self._port}"))
            self._window.setCentralWidget(view)
            self._window.show()
            app.exec()
        except KeyboardInterrupt:
            pass
        finally:
            if self._server:
                self._server.shutdown()
                self._server.server_close()
