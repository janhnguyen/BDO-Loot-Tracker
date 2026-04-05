import subprocess
import sys
from pathlib import Path

from core.log_window import LogWindow
from core.tracker import Tracker
from core.tray import run_tray
from core.local_store import LocalStore
from core.config import (
    LOCAL_DB_PATH,
    SHOW_OCR_LOG,
    ITEMS_FONT_SIZE,
    save_env_setting,
)
from core.parser import get_item_zone, get_item_dehkia_two_zone

def main():
    log_window = None
    local_store = LocalStore(LOCAL_DB_PATH)
    current_session_id = None

    # Event callbacks
    def handle_event(event):
        # Priority: batch context override > Dehkia II zone > CSV zone > current zone
        batch_override = tracker.get_batch_zone_override(event.item_name)
        dehkia_two_zone = get_item_dehkia_two_zone(event.item_name)
        zone_from_item = get_item_zone(event.item_name)

        if batch_override:
            effective_zone = batch_override
        elif dehkia_two_zone:
            effective_zone = dehkia_two_zone
        elif zone_from_item:
            effective_zone = zone_from_item
        else:
            effective_zone = tracker.get_zone()

        if effective_zone and effective_zone != tracker.get_zone():
            tracker.set_zone(effective_zone)
            if current_session_id is not None:
                local_store.update_session_zone(current_session_id, effective_zone)
        event.zone = effective_zone
        if current_session_id is not None:
            local_store.add_event(current_session_id, event)
        log_window.add_event(event)

    def handle_ocr(text):
        log_window.add_raw_ocr(text)

    # Create the tracker
    tracker = Tracker(handle_event, handle_ocr)

    def start_session():
        nonlocal current_session_id
        if tracker.is_running():
            return
        current_session_id = local_store.create_session(tracker.get_zone())
        tracker.start()
        log_window.start_timer()
        log_window.schedule_session_totals_reset(tracker.get_session_reset_delay())
        log_window.refresh_sessions()

    def stop_session():
        nonlocal current_session_id
        if not tracker.is_running():
            return
        tracker.stop()
        log_window.clear_totals()
        elapsed_seconds = log_window.stop_timer()
        if current_session_id is not None:
            local_store.end_session(current_session_id, elapsed_seconds)
            current_session_id = None
        log_window.refresh_sessions()

    def list_sessions():
        return local_store.list_sessions()

    def upload_session(session_id: int):
        rows = local_store.get_unuploaded_events(session_id)
        if not rows:
            return f"Session {session_id}: nothing to upload."
        uploaded_count = local_store.upload_session_events(session_id)
        return f"Session {session_id}: prepared {uploaded_count}/{len(rows)} grouped totals for upload."

    # Status getter for log window
    def get_status():
        return tracker.is_running(), tracker.get_zone()

    def save_ocr_settings(show_ocr: bool):
        save_env_setting("SHOW_OCR_LOG", show_ocr)

    def launch_calibration():
        calibrate_script = Path(__file__).resolve().parent / "helpers" / "calibrate.py"
        subprocess.Popen([sys.executable, str(calibrate_script)], cwd=calibrate_script.parent.parent)
        return "Calibration launched."

    def set_tracking_window(n: int):
        tracker.set_tracking_window_size(n)
        save_env_setting("TRACKING_WINDOW_SIZE", tracker.get_tracking_window_size())

    font_size: int = ITEMS_FONT_SIZE

    def get_font_size() -> int:
        return font_size

    def set_font_size(n: int):
        nonlocal font_size
        font_size = max(12, min(20, int(n)))
        save_env_setting("ITEMS_FONT_SIZE", font_size)

    # Create the log window with start/stop callbacks
    log_window = LogWindow(
        start_cb=start_session,
        stop_cb=stop_session,
        get_status_cb=get_status,
        list_sessions_cb=list_sessions,
        upload_session_cb=upload_session,
        calibrate_cb=launch_calibration,
        show_ocr_default=SHOW_OCR_LOG,
        ocr_settings_changed_cb=save_ocr_settings,
        get_tracking_window_cb=tracker.get_tracking_window_size,
        set_tracking_window_cb=set_tracking_window,
        get_font_size_cb=get_font_size,
        set_font_size_cb=set_font_size,
    )

    # Run tray, passing tracker methods
    run_tray(
        start=start_session,
        stop=stop_session,
        set_zone=tracker.set_zone,
        show_log=log_window.show
    )

    # Run the UI loop
    log_window.run()

if __name__ == "__main__":
    main()
