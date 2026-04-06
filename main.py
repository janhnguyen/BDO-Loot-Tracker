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
    SHOW_OCR_PANE,
    ITEMS_FONT_SIZE,
    save_env_setting,
)
from core.parser import get_item_zone, is_dehkia_two_indicator, get_dehkia_two_upgrade

def main():
    log_window = None
    local_store = LocalStore(LOCAL_DB_PATH)
    current_session_id = None
    pending_dehkia_upgrade = False

    # Event callbacks
    def handle_event(event):
        nonlocal current_session_id, pending_dehkia_upgrade

        batch_override = tracker.get_batch_zone_override(event.item_name)
        current_zone = tracker.get_zone()

        # If a tf=TRUE item arrives, flag that the next [Dehkia] zone should
        # be immediately upgraded to [Dehkia II].
        if is_dehkia_two_indicator(event.item_name):
            if "[Dehkia]" in current_zone:
                dehkia_upgrade = get_dehkia_two_upgrade(current_zone)
            else:
                pending_dehkia_upgrade = True
                dehkia_upgrade = None
        else:
            dehkia_upgrade = None

        zone_from_item = get_item_zone(event.item_name)

        # If we have a pending upgrade and this item resolves a [Dehkia] zone,
        # immediately upgrade to [Dehkia II] and clear the flag.
        if pending_dehkia_upgrade and zone_from_item and "[Dehkia]" in zone_from_item:
            upgrade = get_dehkia_two_upgrade(zone_from_item)
            if upgrade:
                zone_from_item = upgrade
                pending_dehkia_upgrade = False

        # Don't let a [Dehkia] zone from trash loot revert an already-established
        # [Dehkia II] zone for the remainder of the session.
        if "[Dehkia II]" in current_zone and zone_from_item and "[Dehkia]" in zone_from_item:
            zone_from_item = None

        if batch_override:
            effective_zone = batch_override
        elif dehkia_upgrade:
            effective_zone = dehkia_upgrade
        elif zone_from_item:
            effective_zone = zone_from_item
        else:
            effective_zone = current_zone

        if effective_zone and effective_zone != current_zone:
            tracker.set_zone(effective_zone)
            if current_session_id is not None:
                local_store.update_session_zone(current_session_id, effective_zone)
        event.zone = effective_zone
        if current_session_id is not None:
            local_store.add_event(current_session_id, event)
        log_window.add_event(event)

    def handle_ocr(text):
        log_window.add_raw_ocr(text)

    def handle_ocr_frame(raw_img, processed_img):
        log_window.add_ocr_frame(raw_img, processed_img)

    # Create the tracker
    tracker = Tracker(handle_event, handle_ocr, on_ocr_frame=handle_ocr_frame)

    def start_session():
        nonlocal current_session_id
        if tracker.is_running():
            return
        current_session_id = local_store.create_session(tracker.get_zone())
        tracker.start()
        log_window.start_timer()
        log_window.schedule_session_totals_reset(tracker.get_session_reset_delay())
        log_window.refresh_sessions()

    def pause_session():
        if not tracker.is_running() or tracker.is_paused():
            return
        tracker.pause()
        log_window.pause_timer()

    def resume_session():
        if not tracker.is_running() or not tracker.is_paused():
            return
        tracker.resume()
        log_window.resume_timer()

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

    def save_ocr_pane_settings(show_ocr_pane: bool):
        save_env_setting("SHOW_OCR_PANE", show_ocr_pane)

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

    def get_db_stats():
        return local_store.get_db_stats()

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
        show_ocr_pane_default=SHOW_OCR_PANE,
        ocr_pane_settings_changed_cb=save_ocr_pane_settings,
        get_tracking_window_cb=tracker.get_tracking_window_size,
        set_tracking_window_cb=set_tracking_window,
        get_font_size_cb=get_font_size,
        set_font_size_cb=set_font_size,
        get_db_stats_cb=get_db_stats,
        pause_cb=pause_session,
        resume_cb=resume_session,
        is_paused_cb=tracker.is_paused,
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
