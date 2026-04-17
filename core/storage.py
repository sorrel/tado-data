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


def _migrate_entry(entry: dict) -> dict:
    """Migrate old {state, since} format to {good_since, low_since}."""
    if "state" in entry:
        state = entry["state"]
        since = entry.get("since")
        if state == "NORMAL":
            return {"good_since": since, "low_since": None}
        else:
            return {"good_since": None, "low_since": since}
    return entry


def load_battery_history() -> dict:
    """Return stored battery state history keyed by device serial number."""
    raw = _load_json(BATTERY_HISTORY_FILE).get("devices", {})
    return {serial: _migrate_entry(entry) for serial, entry in raw.items()}


def update_battery_history(current_states: dict[str, str]) -> dict:
    """
    Update battery history with current states.

    Tracks good_since (last time battery became NORMAL) and
    low_since (when it went LOW) independently, so neither is
    lost when the state changes.

    current_states: {serial: "NORMAL" | "LOW"}
    Returns updated history dict.
    """
    history = load_battery_history()
    today = date.today().isoformat()
    changed = False

    for serial, state in current_states.items():
        entry = history.get(serial, {})
        prev_good = entry.get("good_since")
        prev_low = entry.get("low_since")

        if state == "NORMAL":
            # Went from LOW → NORMAL (or first time seen as NORMAL)
            new_good = prev_good if prev_good else today
            new_low = None
        else:
            # Went from NORMAL → LOW (or first time seen as LOW)
            new_good = prev_good  # preserve — this is how long the battery lasted
            new_low = prev_low if prev_low else today

        new_entry = {"good_since": new_good, "low_since": new_low}
        if new_entry != entry:
            history[serial] = new_entry
            changed = True
        elif serial not in history:
            history[serial] = new_entry
            changed = True

    if changed:
        _save_json(BATTERY_HISTORY_FILE, {"devices": history})

    return history
