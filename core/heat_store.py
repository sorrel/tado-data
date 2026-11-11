"""
Local store for the heat check: saved day reports and the check's state.

Day reports are saved so a day is never fetched twice. The state records the
last day checked and which faults are known, for the once-a-week repeat.
Both live in stored_data/ (gitignored) and are saved atomically.
"""

import os
from datetime import date

from core.storage import STORED_DATA_DIR, _load_json, _save_json

DAY_REPORTS_DIR = os.path.join(STORED_DATA_DIR, "day_reports")
HEAT_STATE_FILE = os.path.join(STORED_DATA_DIR, "heat_check.json")


def _day_report_path(day: date, zone_id: int) -> str:
    return os.path.join(DAY_REPORTS_DIR, day.isoformat(), f"{zone_id}.json")


def load_day_report(day: date, zone_id: int) -> dict | None:
    """The saved report, or None if it hasn't been fetched. Raises BatteryHistoryError if damaged."""
    path = _day_report_path(day, zone_id)
    if not os.path.exists(path):
        return None
    return _load_json(path)


def save_day_report(day: date, zone_id: int, report: dict) -> None:
    _save_json(_day_report_path(day, zone_id), report)


def load_state() -> dict:
    """
    {"last_checked": "YYYY-MM-DD" | None, "faults": {"<zone_id>:<kind>": {...}}}.

    Raises BatteryHistoryError if the file is damaged, so it's never replaced
    by an empty state.
    """
    state = _load_json(HEAT_STATE_FILE)
    return {"last_checked": state.get("last_checked"), "faults": state.get("faults", {})}


def save_state(state: dict) -> None:
    _save_json(HEAT_STATE_FILE, state)
