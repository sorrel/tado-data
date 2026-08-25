"""
Tests for battery history storage.

The point of update_battery_history is that good_since and low_since are
tracked independently, so a battery going flat doesn't erase the record of
how long it lasted. Most of what follows pins down that behaviour.
"""

import json

from core.storage import load_battery_history, update_battery_history

SERIAL = "VA1234567890"


def _write(path, devices):
    """Seed the history file directly, as a previous run would have left it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"devices": devices}))


# --- first sighting of a device ------------------------------------------


def test_new_normal_device_records_good_since_today(frozen_today, history_file):
    history = update_battery_history({SERIAL: "NORMAL"})

    assert history[SERIAL] == {"good_since": "2026-08-25", "low_since": None}


def test_new_low_device_records_low_since_today(frozen_today, history_file):
    history = update_battery_history({SERIAL: "LOW"})

    assert history[SERIAL] == {"good_since": None, "low_since": "2026-08-25"}


# --- state transitions ----------------------------------------------------


def test_normal_to_low_preserves_good_since(frozen_today, history_file):
    """The whole point: we keep how long the battery lasted before it died."""
    _write(history_file, {SERIAL: {"good_since": "2025-01-10", "low_since": None}})

    history = update_battery_history({SERIAL: "LOW"})

    assert history[SERIAL] == {
        "good_since": "2025-01-10",  # untouched
        "low_since": "2026-08-25",
    }


def test_low_to_normal_resets_good_since_and_clears_low(frozen_today, history_file):
    """A LOW -> NORMAL transition means the battery was replaced."""
    _write(history_file, {SERIAL: {"good_since": "2025-01-10", "low_since": "2026-06-01"}})

    history = update_battery_history({SERIAL: "NORMAL"})

    assert history[SERIAL] == {"good_since": "2026-08-25", "low_since": None}


def test_normal_stays_normal_does_not_bump_good_since(frozen_today, history_file):
    """A routine check-in must not restart the clock."""
    _write(history_file, {SERIAL: {"good_since": "2025-01-10", "low_since": None}})

    history = update_battery_history({SERIAL: "NORMAL"})

    assert history[SERIAL]["good_since"] == "2025-01-10"


def test_low_stays_low_does_not_bump_low_since(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2025-01-10", "low_since": "2026-06-01"}})

    history = update_battery_history({SERIAL: "LOW"})

    assert history[SERIAL]["low_since"] == "2026-06-01"


# --- persistence ----------------------------------------------------------


def test_history_is_written_to_disk_and_reloads(frozen_today, history_file):
    update_battery_history({SERIAL: "NORMAL"})

    assert history_file.exists()
    assert load_battery_history() == {
        SERIAL: {"good_since": "2026-08-25", "low_since": None}
    }


def test_multiple_devices_tracked_independently(frozen_today, history_file):
    history = update_battery_history({"AAA": "NORMAL", "BBB": "LOW"})

    assert history["AAA"] == {"good_since": "2026-08-25", "low_since": None}
    assert history["BBB"] == {"good_since": None, "low_since": "2026-08-25"}


# --- legacy format migration ---------------------------------------------


def test_migrates_legacy_normal_entry(frozen_today, history_file):
    """Old format was a single {state, since} pair."""
    _write(history_file, {SERIAL: {"state": "NORMAL", "since": "2025-03-01"}})

    assert load_battery_history()[SERIAL] == {
        "good_since": "2025-03-01",
        "low_since": None,
    }


def test_migrates_legacy_low_entry(frozen_today, history_file):
    _write(history_file, {SERIAL: {"state": "LOW", "since": "2025-03-01"}})

    assert load_battery_history()[SERIAL] == {
        "good_since": None,
        "low_since": "2025-03-01",
    }


# --- degenerate files -----------------------------------------------------


def test_missing_file_returns_empty_history(frozen_today, history_file):
    assert not history_file.exists()
    assert load_battery_history() == {}


def test_corrupt_file_returns_empty_history(frozen_today, history_file):
    history_file.parent.mkdir(parents=True, exist_ok=True)
    history_file.write_text("{ not json at all")

    assert load_battery_history() == {}
