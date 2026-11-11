"""
Tests for the heat check's local store: saved day reports and check state.
"""

from datetime import date
from pathlib import Path

import pytest

from core.heat_store import load_day_report, load_state, save_day_report, save_state
from core.storage import BatteryHistoryError

DAY = date(2026, 11, 10)


def test_day_report_round_trip(heat_store_dir):
    save_day_report(DAY, 12, {"zoneType": "HEATING"})
    assert load_day_report(DAY, 12) == {"zoneType": "HEATING"}
    assert (heat_store_dir / "day_reports" / "2026-11-10" / "12.json").exists()


def test_missing_day_report_is_none(heat_store_dir):
    assert load_day_report(DAY, 12) is None


def test_state_defaults_when_absent(heat_store_dir):
    assert load_state() == {"last_checked": None, "faults": {}}


def test_state_round_trip_keeps_backup(heat_store_dir):
    save_state({"last_checked": "2026-11-09", "faults": {}})
    state = {"last_checked": "2026-11-10", "faults": {"12:offline": {"zone": "Downstairs Loo"}}}
    save_state(state)
    assert load_state() == state
    assert (heat_store_dir / "heat_check.json.bak").exists()


def test_damaged_state_file_is_refused(heat_store_dir):
    path = heat_store_dir / "heat_check.json"
    path.write_text("{")
    with pytest.raises(BatteryHistoryError):
        load_state()
    assert path.read_text() == "{"


def test_damaged_day_report_is_refused(heat_store_dir):
    folder = heat_store_dir / "day_reports" / "2026-11-10"
    folder.mkdir(parents=True)
    (folder / "12.json").write_text("not json")
    with pytest.raises(BatteryHistoryError):
        load_day_report(DAY, 12)
