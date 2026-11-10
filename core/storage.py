"""
Persistent local storage for data that accumulates over time.
Stored in stored_data/ directory, gitignored.
"""

import json
import os
import shutil
from datetime import date

import click

STORED_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "stored_data")
BATTERY_HISTORY_FILE = os.path.join(STORED_DATA_DIR, "battery_history.json")

# The day tracking began. Batteries dated on or before this were already fitted,
# so their real age is unknown and any lifespan measured from it is a minimum.
TRACKING_STARTED = "2026-04-17"


class BatteryHistoryError(click.ClickException):
    """The history file can't be read. Carrying on would overwrite it."""


def _load_json(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError as error:  # bad JSON, or bytes that aren't text
        raise BatteryHistoryError(
            f"{path} is damaged, so nothing has been changed. "
            f"Restore it from {path}.bak or your own backup. ({error})"
        ) from error


def _save_json(path: str, data: dict) -> None:
    """Save so that a failure part-way leaves the file intact, keeping the last version as .bak."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        shutil.copy2(path, f"{path}.bak")
    os.replace(temporary, path)


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


def _retired_battery(fitted: str, went_low: str, replaced: str, died: str | None) -> dict | None:
    """Build the permanent record of a replaced battery, or None if its dates are unusable."""
    try:
        days = (date.fromisoformat(went_low) - date.fromisoformat(fitted)).days
    except ValueError:
        return None
    record = {
        "fitted": fitted,
        "went_low": went_low,
        "replaced": replaced,
        "days": days,
        "minimum": fitted <= TRACKING_STARTED,
    }
    if died:
        record["died"] = died
    return record


def mark_battery_replaced(serial: str) -> dict | None:
    """
    Record that the user has replaced a device's batteries, and restart its clock.

    Returns the saved record of the old battery, or None if it never went
    LOW or its dates are unusable, so there is no lifespan to keep.
    Raises KeyError if the device has no history.
    """
    history = load_battery_history()
    entry = history[serial]
    today = date.today().isoformat()
    past = list(entry.get("past_batteries", []))

    retired = None
    if entry.get("good_since") and entry.get("low_since"):
        retired = _retired_battery(entry["good_since"], entry["low_since"], today, entry.get("died"))
    if retired:
        if entry.get("low_periods"):
            retired["low_periods"] = entry["low_periods"]
        past.append(retired)

    new_entry = {"good_since": today, "low_since": None}
    if past:
        new_entry["past_batteries"] = past
    history[serial] = new_entry
    _save_json(BATTERY_HISTORY_FILE, {"devices": history})
    return retired


def update_battery_history(current_states: dict[str, str], disconnected: set[str] | None = None) -> dict:
    """
    Update battery history with current states.

    Tracks good_since (last time battery became NORMAL) and
    low_since (when it went LOW) independently, so neither is
    lost when the state changes. Replacements are never inferred here;
    see mark_battery_replaced.

    A LOW device that is offline is taken to have died, and the first date
    that is seen is kept in died. If it comes back online it wasn't dead,
    so the date is cleared.

    current_states: {serial: "NORMAL" | "LOW"}
    disconnected: serials currently offline
    Returns updated history dict.
    """
    disconnected = disconnected or set()
    history = load_battery_history()
    today = date.today().isoformat()
    changed = False

    for serial, state in current_states.items():
        entry = history.get(serial, {})
        prev_good = entry.get("good_since")
        prev_low = entry.get("low_since")
        prev_died = entry.get("died")
        past = list(entry.get("past_batteries", []))
        new_died = None

        periods = [dict(period) for period in entry.get("low_periods", [])]
        if prev_low and not periods:
            # A low date saved before low spells were recorded
            periods = [{"from": prev_low, "to": None}]

        if state == "NORMAL":
            # Going back to NORMAL proves nothing: the same batteries may have gone
            # back in. Only mark_battery_replaced restarts the clock.
            new_good = prev_good if prev_low else (prev_good or today)
            new_low = prev_low
            if periods and periods[-1]["to"] is None:
                periods[-1]["to"] = today
        else:
            # Went from NORMAL → LOW (or first time seen as LOW)
            new_good = prev_good  # preserve — this is how long the battery lasted
            # A LOW reading on the day of fitting is Tado still reporting the old state
            new_low = prev_low or (None if prev_good == today else today)
            if new_low and (not periods or periods[-1]["to"] is not None):
                periods.append({"from": today, "to": None})
            if serial in disconnected:
                new_died = prev_died or today

        new_entry = {"good_since": new_good, "low_since": new_low}
        if new_died:
            new_entry["died"] = new_died
        if periods:
            new_entry["low_periods"] = periods
        if past:
            new_entry["past_batteries"] = past
        if new_entry != entry:
            history[serial] = new_entry
            changed = True
        elif serial not in history:
            history[serial] = new_entry
            changed = True

    if changed:
        _save_json(BATTERY_HISTORY_FILE, {"devices": history})

    return history
