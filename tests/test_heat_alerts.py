"""
Tests for when a heat-check fault is notified: new, weekly, cleared.
"""

import copy
from datetime import date, timedelta

from core.heat_alerts import update_faults

DAY = date(2026, 11, 10)
LOO_OFFLINE = {"12:offline": ("Downstairs Loo", "offline")}
LOO_WARMING = {"12:warming": ("Downstairs Loo", "warming")}


def _run(days, current):
    """Check the same faults on each of `days` in turn; return the final faults and lines sent."""
    faults, sent = {}, []
    for day in days:
        faults, lines = update_faults(faults, day, current)
        sent.append(lines)
    return faults, sent


def test_new_fault_notifies():
    faults, lines = update_faults({}, DAY, LOO_OFFLINE)
    assert lines == ["Downstairs Loo is offline"]
    assert faults["12:offline"] == {
        "zone": "Downstairs Loo",
        "kind": "offline",
        "first_seen": "2026-11-10",
        "last_seen": "2026-11-10",
        "last_notified": "2026-11-10",
    }


def test_new_warming_wording():
    _, lines = update_faults({}, DAY, LOO_WARMING)
    assert lines == ["Downstairs Loo warmed with the heating off"]


def test_known_fault_is_quiet_for_six_days():
    _, sent = _run([DAY + timedelta(days=n) for n in range(7)], LOO_OFFLINE)
    assert sent[0] == ["Downstairs Loo is offline"]
    assert sent[1:] == [[]] * 6


def test_known_fault_repeats_on_day_seven():
    faults, sent = _run([DAY + timedelta(days=n) for n in range(8)], LOO_OFFLINE)
    assert sent[7] == ["Downstairs Loo is offline"]
    assert faults["12:offline"]["last_notified"] == "2026-11-17"
    assert faults["12:offline"]["first_seen"] == "2026-11-10"
    assert faults["12:offline"]["last_seen"] == "2026-11-17"


def test_cleared_offline_says_back_online():
    faults, _ = update_faults({}, DAY, LOO_OFFLINE)
    faults, lines = update_faults(faults, DAY + timedelta(days=1), {})
    assert lines == ["Downstairs Loo is back online"]
    assert faults == {}


def test_cleared_warming_wording():
    faults, _ = update_faults({}, DAY, LOO_WARMING)
    _, lines = update_faults(faults, DAY + timedelta(days=1), {})
    assert lines == ["Downstairs Loo has stopped warming with the heating off"]


def test_two_zones_are_independent():
    faults, _ = update_faults({}, DAY, LOO_OFFLINE)
    both = {**LOO_OFFLINE, "3:warming": ("Hall", "warming")}
    faults, lines = update_faults(faults, DAY + timedelta(days=1), both)
    assert lines == ["Hall warmed with the heating off"]
    assert set(faults) == {"12:offline", "3:warming"}


def test_input_is_not_mutated():
    faults, _ = update_faults({}, DAY, LOO_OFFLINE)
    before = copy.deepcopy(faults)
    update_faults(faults, DAY + timedelta(days=7), LOO_OFFLINE)
    update_faults(faults, DAY + timedelta(days=1), {})
    assert faults == before
