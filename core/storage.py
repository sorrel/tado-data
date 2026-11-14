"""
Persistent local storage for data that accumulates over time.
Stored in stored_data/ directory, gitignored.
"""

import json
import os
import shutil
from datetime import date
from typing import NotRequired, TypedDict, cast

import click

STORED_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "stored_data")
BATTERY_HISTORY_FILE = os.path.join(STORED_DATA_DIR, "battery_history.json")
# Which room each device was in when last seen, so tab completion can offer
# room names without asking Tado. A convenience only: losing it costs nothing.
ROOM_NAMES_FILE = os.path.join(STORED_DATA_DIR, "room_names.json")

# The day tracking began. Batteries dated on or before this were already fitted,
# so their real age is unknown and any lifespan measured from it is a minimum.
TRACKING_STARTED = "2026-04-17"


# --- What battery_history.json holds -----------------------------------------
# Dates are ISO strings (YYYY-MM-DD), as saved in the file.

# One spell of LOW. "from" is a keyword, so this needs the functional form.
# to: None while still low. seen: the last day it was seen LOW (absent on older spells).
LowPeriod = TypedDict("LowPeriod", {"from": str, "to": str | None, "seen": NotRequired[str]})


class MeterReading(TypedDict):
    date: str
    percent: list[int]  # one per cell
    note: NotRequired[str]


class Lifespan(TypedDict):
    days: int
    minimum: bool  # days is only a lower bound: unknown age, or not yet at the end


class PastBattery(Lifespan):
    """A set that has been taken out. days runs from fitted to went_low, or to replaced."""

    fitted: str
    went_low: str | None  # None: taken out before it ever warned
    replaced: str
    make: NotRequired[str]  # brand of the AA cells, when known
    died: NotRequired[str]  # first day seen offline while LOW
    low_periods: NotRequired[list[LowPeriod]]
    meter_readings: NotRequired[list[MeterReading]]


class DeviceHistory(TypedDict):
    """The batteries now in one device, and every set taken out before them."""

    good_since: str | None  # when these batteries were fitted (or tracking began)
    low_since: str | None  # first low warning; kept even if it goes back to NORMAL
    make: NotRequired[str]  # brand of the AA cells now fitted, when known
    died: NotRequired[str]
    low_periods: NotRequired[list[LowPeriod]]
    meter_readings: NotRequired[list[MeterReading]]
    past_batteries: NotRequired[list[PastBattery]]


type BatteryHistory = dict[str, DeviceHistory]  # keyed by device serial

# The entry of a device seen for the first time.
NEW_DEVICE: DeviceHistory = {"good_since": None, "low_since": None}


class BatteryHistoryError(click.ClickException):
    """The history file can't be read. Carrying on would overwrite it."""


class NoOldBatteries(Exception):
    """A reading was meant for batteries already taken out, but none have been."""


class AlreadyReplacedToday(Exception):
    """The batteries were marked as replaced earlier today and haven't warned since."""


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


def _migrate_entry(entry: dict) -> DeviceHistory:
    """Migrate old {state, since} format to {good_since, low_since}."""
    if "state" in entry:
        state = entry["state"]
        since = entry.get("since")
        if state == "NORMAL":
            return {"good_since": since, "low_since": None}
        else:
            return {"good_since": None, "low_since": since}
    return cast(DeviceHistory, entry)  # written by this module, so already in shape


def load_battery_history() -> BatteryHistory:
    """Return stored battery state history keyed by device serial number."""
    raw = _load_json(BATTERY_HISTORY_FILE).get("devices", {})
    return {serial: _migrate_entry(entry) for serial, entry in raw.items()}


def _retired_battery(
    fitted: str, went_low: str | None, replaced: str, died: str | None
) -> PastBattery | None:
    """
    Build the permanent record of a replaced battery, or None if its dates are unusable.

    A battery taken out before it ever warned has no time to first low; how
    long it was in is kept instead, as a minimum, with went_low None.
    """
    try:
        days = (date.fromisoformat(went_low or replaced) - date.fromisoformat(fitted)).days
    except ValueError:
        return None
    record: PastBattery = {
        "fitted": fitted,
        "went_low": went_low,
        "replaced": replaced,
        "days": days,
        "minimum": went_low is None or fitted <= TRACKING_STARTED,
    }
    if died:
        record["died"] = died
    return record


def replaced_today(entry: DeviceHistory) -> bool:
    """Whether these batteries were fitted today and haven't warned since."""
    return entry.get("good_since") == date.today().isoformat() and not entry.get("low_since")


def known_makes(history: BatteryHistory) -> list[str]:
    """Every battery make recorded so far, in alphabetical order."""
    makes = {entry["make"] for entry in history.values() if "make" in entry}
    makes |= {
        battery["make"]
        for entry in history.values()
        for battery in entry.get("past_batteries", [])
        if "make" in battery
    }
    return sorted(makes, key=str.casefold)


def tidy_make(make: str | None, history: BatteryHistory) -> str | None:
    """
    MAKE with spare spaces removed, spelt as before if it was recorded already.

    "duracell" becomes "Duracell" once Duracell is known, so one make isn't
    counted as two. A blank make is None.
    """
    make = " ".join((make or "").split())
    if not make:
        return None
    for known in known_makes(history):
        if known.casefold() == make.casefold():
            return known
    return make


def mark_battery_replaced(
    serial: str, make: str | None = None, old_make: str | None = None
) -> PastBattery | None:
    """
    Record that the user has replaced a device's batteries, and restart its clock.

    MAKE is the brand of the new batteries. OLD_MAKE is the brand of the ones
    taken out, used only if it wasn't recorded when they went in.

    Returns the saved record of the old battery, or None if its dates are
    unusable. A battery that never went LOW is kept as a minimum lifespan.
    Raises KeyError if the device has no history, and AlreadyReplacedToday if
    this is a repeat of today's replacement, which would otherwise save a
    0-day battery.
    """
    history = load_battery_history()
    entry = history[serial]
    today = date.today().isoformat()
    if replaced_today(entry):
        raise AlreadyReplacedToday(serial)
    make = tidy_make(make, history)
    old_make = entry.get("make") or tidy_make(old_make, history)

    past = list(entry.get("past_batteries", []))
    retired = None
    if fitted := entry.get("good_since"):
        retired = _retired_battery(fitted, entry.get("low_since"), today, entry.get("died"))
    if retired:
        # Spells of LOW and meter readings belong to this set, so they go with it.
        # A spell still open ends today: these batteries can't be low any longer.
        if periods := entry.get("low_periods"):
            retired["low_periods"] = [
                period if period["to"] else {**period, "to": today} for period in periods
            ]
        if readings := entry.get("meter_readings"):
            retired["meter_readings"] = readings
        if old_make:
            retired["make"] = old_make
        past.append(retired)

    new_entry: DeviceHistory = {"good_since": today, "low_since": None}
    if make:
        new_entry["make"] = make
    if past:
        new_entry["past_batteries"] = past
    history[serial] = new_entry
    _save_json(BATTERY_HISTORY_FILE, {"devices": history})
    return retired


def set_battery_make(serial: str, make: str, old_set: bool = False) -> tuple[str, str | None]:
    """
    Record or correct the make of the batteries now in device SERIAL.

    With old_set it goes on the set most recently taken out instead.
    Returns the make as saved, and the day that set came out (None for the
    batteries now fitted). Raises KeyError if the device has no history,
    NoOldBatteries if old_set is asked for but nothing has been replaced, and
    ValueError if MAKE is blank.
    """
    history = load_battery_history()
    entry = history[serial]
    tidied = tidy_make(make, history)
    if not tidied:
        raise ValueError("blank make")
    if not old_set:
        history[serial] = {**entry, "make": tidied}
        _save_json(BATTERY_HISTORY_FILE, {"devices": history})
        return tidied, None
    past = list(entry.get("past_batteries", []))
    if not past:
        raise NoOldBatteries(serial)
    past[-1] = {**past[-1], "make": tidied}
    history[serial] = {**entry, "past_batteries": past}
    _save_json(BATTERY_HISTORY_FILE, {"devices": history})
    return tidied, past[-1]["replaced"]


def _with_reading[R: (DeviceHistory, PastBattery)](record: R, reading: MeterReading) -> R:
    """A copy of RECORD with READING added to its meter readings, kept in date order."""
    updated = record.copy()
    readings = [*record.get("meter_readings", []), reading]
    updated["meter_readings"] = sorted(readings, key=lambda r: r["date"])
    return updated


def add_meter_reading(
    serial: str,
    percents: list[int],
    on: str | None = None,
    note: str | None = None,
    old_set: bool = False,
) -> tuple[MeterReading, str | None]:
    """
    Record what a battery meter said about the cells in device SERIAL.

    One percentage per cell. Tado only reports NORMAL or LOW, so these are the
    only measure of how much charge was really left when it warned.

    Normally the reading belongs to the batteries now fitted. With old_set it
    goes on the set most recently taken out, dated the day they came out
    unless ON says otherwise, for a reading not recorded before
    battery-replaced.

    Returns the saved reading, and the day the set it went on was taken out
    (None for the batteries now fitted). Raises KeyError if the device has no
    history, and NoOldBatteries if old_set is asked for but nothing has been
    replaced.
    """
    history = load_battery_history()
    entry = history[serial]
    past = list(entry.get("past_batteries", []))
    if old_set and not past:
        raise NoOldBatteries(serial)
    replaced = past[-1]["replaced"] if old_set else None

    reading: MeterReading = {
        "date": on or replaced or date.today().isoformat(),
        "percent": list(percents),
    }
    if note:
        reading["note"] = note
    if old_set:
        past[-1] = _with_reading(past[-1], reading)
        history[serial] = {**entry, "past_batteries": past}
    else:
        history[serial] = _with_reading(entry, reading)
    _save_json(BATTERY_HISTORY_FILE, {"devices": history})
    return reading, replaced


def update_battery_history(
    current_states: dict[str, str], disconnected: set[str] | None = None
) -> BatteryHistory:
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
        entry = history.get(serial, NEW_DEVICE)
        new_entry = _updated_entry(entry, state, serial in disconnected, today)
        if serial not in history or new_entry != entry:
            history[serial] = new_entry
            changed = True

    if changed:
        _save_json(BATTERY_HISTORY_FILE, {"devices": history})

    return history


def _updated_entry(entry: DeviceHistory, state: str, offline: bool, today: str) -> DeviceHistory:
    """One device's history entry after seeing it in STATE today."""
    prev_good = entry.get("good_since")
    prev_low = entry.get("low_since")
    new_died = None

    periods: list[LowPeriod] = [period.copy() for period in entry.get("low_periods", [])]
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
        if new_low and periods:
            periods[-1]["seen"] = today
        if offline:
            new_died = entry.get("died") or today

    new_entry: DeviceHistory = {"good_since": new_good, "low_since": new_low}
    if make := entry.get("make"):
        new_entry["make"] = make
    if new_died:
        new_entry["died"] = new_died
    if periods:
        new_entry["low_periods"] = periods
    # The make, readings and past batteries are only ever changed by their own commands.
    if readings := entry.get("meter_readings"):
        new_entry["meter_readings"] = readings
    if past := entry.get("past_batteries"):
        new_entry["past_batteries"] = past
    return new_entry


def save_room_names(device_zones: dict[str, str]) -> None:
    """
    Remember which room each device is in.

    Failing to save is harmless, so it is never an error.
    """
    if not device_zones:
        return
    try:
        if _load_room_names() != device_zones:
            _save_json(ROOM_NAMES_FILE, device_zones)
    except OSError:
        pass


def _load_room_names() -> dict[str, str]:
    try:
        with open(ROOM_NAMES_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_room_names() -> dict[str, str]:
    """Return the last saved serial-to-room map, or an empty one if there is none."""
    return _load_room_names()
