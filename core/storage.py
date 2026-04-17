"""
Persistent local storage for data that accumulates over time.
Stored in stored_data/ directory, gitignored.
"""

import json
import os
from datetime import date

STORED_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "stored_data")
BATTERY_HISTORY_FILE = os.path.join(STORED_DATA_DIR, "battery_history.json")


def _load_json(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_battery_history() -> dict:
    """Return stored battery state history keyed by device serial number."""
    return _load_json(BATTERY_HISTORY_FILE).get("devices", {})


def update_battery_history(current_states: dict[str, str]) -> dict:
    """
    Compare current battery states against stored history.
    Records a new 'since' date whenever a device's state changes.

    current_states: {serial: "NORMAL" | "LOW"}
    Returns updated history dict.
    """
    history = load_battery_history()
    today = date.today().isoformat()
    changed = False

    for serial, state in current_states.items():
        entry = history.get(serial)
        if entry is None or entry.get("state") != state:
            history[serial] = {"state": state, "since": today}
            changed = True

    if changed:
        _save_json(BATTERY_HISTORY_FILE, {"devices": history})

    return history
