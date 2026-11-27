"""
Local store for the heat check: saved day reports and the check's state.

Day reports are saved so a day is never fetched twice. The state records the
last day checked and which faults are known, for the once-a-week repeat.
Both live in stored_data/ (gitignored) and are saved atomically.
"""

import os
from datetime import date

from tado_data.core.jsonfile import load_json, save_json
from tado_data.core.paths import STORED_DATA_DIR

DAY_REPORTS_DIR = os.path.join(STORED_DATA_DIR, "day_reports")
HEAT_STATE_FILE = os.path.join(STORED_DATA_DIR, "heat_check.json")


def _day_report_path(day: date, zone_id: int) -> str:
    # The zone id comes from Tado's reply and goes into the file name, so
    # refuse anything but a whole number: a string such as "../x" would
    # otherwise write outside stored_data/.
    if type(zone_id) is not int:  # not isinstance: True is an int too
        raise ValueError(f"Tado gave a zone id that isn't a whole number: {zone_id!r}")
    return os.path.join(DAY_REPORTS_DIR, day.isoformat(), f"{zone_id}.json")


def load_day_report(day: date, zone_id: int) -> dict | None:
    """
    The saved report, or None if it hasn't been fetched.

    Raises DamagedFile if it is damaged.
    """
    path = _day_report_path(day, zone_id)
    if not os.path.exists(path):
        return None
    return load_json(path)


def save_day_report(day: date, zone_id: int, report: dict) -> None:
    save_json(_day_report_path(day, zone_id), report)


def load_state() -> dict:
    """
    {"last_checked": "YYYY-MM-DD" | None, "faults": {"<zone_id>:<kind>": {...}},
     "battery_checked": "YYYY-MM-DD" | None}.

    battery_checked is the last day the batteries were checked (today, not
    yesterday: battery state is a reading of now, not a day report).

    Raises DamagedFile if the file is damaged, so it's never replaced
    by an empty state.
    """
    state = load_json(HEAT_STATE_FILE)
    return {
        "last_checked": state.get("last_checked"),
        "faults": state.get("faults", {}),
        "battery_checked": state.get("battery_checked"),
    }


def save_state(state: dict) -> None:
    save_json(HEAT_STATE_FILE, state)
