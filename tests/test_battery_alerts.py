"""Tests for which battery changes the scheduled check notifies."""

from tado_data.core.battery_alerts import battery_changes

LABELS = {"VA1": "Loo valve"}
NORMAL = {"good_since": "2026-04-17", "low_since": None}
LOW = {
    "good_since": "2026-04-17",
    "low_since": "2026-11-09",
    "low_periods": [{"from": "2026-11-09", "to": None, "seen": "2026-11-09"}],
}


def test_nothing_changed_is_silent():
    assert battery_changes({"VA1": NORMAL}, {"VA1": NORMAL}, LABELS) == []


def test_another_day_on_low_is_silent():
    later = {**LOW, "low_periods": [{"from": "2026-11-09", "to": None, "seen": "2026-11-10"}]}
    assert battery_changes({"VA1": LOW}, {"VA1": later}, LABELS) == []


def test_going_low():
    assert battery_changes({"VA1": NORMAL}, {"VA1": LOW}, LABELS) == ["Loo valve batteries are low"]


def test_a_new_device_seen_low():
    assert battery_changes({}, {"VA1": LOW}, LABELS) == ["Loo valve batteries are low"]


def test_back_to_normal():
    normal = {**LOW, "low_periods": [{"from": "2026-11-09", "to": "2026-11-10"}]}
    assert battery_changes({"VA1": LOW}, {"VA1": normal}, LABELS) == [
        "Loo valve batteries are back to normal"
    ]


def test_legacy_low_since_without_spells_counts_as_low():
    legacy = {"good_since": "2026-04-17", "low_since": "2026-11-09"}
    assert battery_changes({"VA1": legacy}, {"VA1": LOW}, LABELS) == []


def test_died_and_back_online():
    dead = {**LOW, "died": "2026-11-10"}
    assert battery_changes({"VA1": LOW}, {"VA1": dead}, LABELS) == [
        "Loo valve has gone offline with low batteries"
    ]
    assert battery_changes({"VA1": dead}, {"VA1": LOW}, LABELS) == ["Loo valve is back online"]


def test_falls_back_to_the_serial():
    assert battery_changes({}, {"VA9": LOW}, {}) == ["VA9 batteries are low"]
