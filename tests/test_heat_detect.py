"""
Tests for finding problems in a Tado day report.

dayreport_fault.json is the real Downstairs Loo report for 10 November 2026,
the day its stuck valve heated the room with Tado off (weather removed).
Everything else is a small hand-made report.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.heat_detect import day_window, find_problems

FIXTURE = Path(__file__).parent / "fixtures" / "dayreport_fault.json"
DAY = date(2026, 11, 10)  # GMT, so local times equal UTC


def load_fixture():
    return json.loads(FIXTURE.read_text())


def utc(*parts):
    return datetime(*parts, tzinfo=timezone.utc)


def at(hhmm, day="2026-11-10"):
    return f"{day}T{hhmm}:00.000Z"


def make_report(points=(), calls=(("00:00", "next", "NONE"),), connected=None):
    """
    A minimal day report for DAY.

    points: (HH:MM, °C); calls and connected: (from HH:MM, to HH:MM or "next", value).
    "next" means midnight at the end of the day.
    """

    def end(hhmm):
        return "2026-11-11T00:00:00.000Z" if hhmm == "next" else at(hhmm)

    report = {
        "measuredData": {
            "insideTemperature": {
                "dataPoints": [{"timestamp": at(t), "value": {"celsius": c}} for t, c in points],
            },
        },
        "callForHeat": {
            "dataIntervals": [{"from": at(a), "to": end(b), "value": v} for a, b, v in calls]
        },
    }
    if connected is not None:
        report["measuredData"]["measuringDeviceConnected"] = {
            "dataIntervals": [{"from": at(a), "to": end(b), "value": v} for a, b, v in connected],
        }
    return report


def kinds(found):
    return [f.kind for f in found]


# --- the real fault day -----------------------------------------------------


def test_fault_day_flags_the_loo():
    warming = [f for f in find_problems(load_fixture(), DAY) if f.kind == "warming"]
    assert len(warming) == 1
    assert warming[0].rise == pytest.approx(6.62, abs=0.01)
    assert warming[0].low == pytest.approx(18.56)
    assert warming[0].start == utc(2026, 11, 10, 10, 0)
    assert warming[0].high == pytest.approx(25.18)
    assert warming[0].end == utc(2026, 11, 10, 18, 0)


def test_fault_day_reports_offline_from_1935():
    offline = [f for f in find_problems(load_fixture(), DAY) if f.kind == "offline"]
    assert len(offline) == 1
    assert offline[0].start == utc(2026, 11, 10, 19, 35, 55)


# --- warming ------------------------------------------------------------------


def test_warm_room_without_a_rise_is_not_flagged():
    report = make_report([(f"{h:02d}:00", 24.0) for h in range(24)])
    assert find_problems(report, DAY) == []


def test_rise_inside_the_carry_over_is_ignored():
    report = make_report(
        [("05:30", 17.0), ("06:05", 17.0), ("06:25", 20.0), ("07:00", 20.0), ("09:00", 20.0)],
        calls=[("00:00", "06:00", "HIGH"), ("06:00", "next", "NONE")],
    )
    assert find_problems(report, DAY) == []


def test_rise_just_after_the_carry_over_is_flagged():
    report = make_report(
        [("06:35", 17.0), ("07:00", 19.0)],
        calls=[("00:00", "06:00", "HIGH"), ("06:00", "next", "NONE")],
    )
    assert kinds(find_problems(report, DAY)) == ["warming"]


def test_rise_just_under_threshold_is_not_flagged():
    report = make_report([("08:00", 18.0), ("12:00", 19.9)])
    assert find_problems(report, DAY) == []


def test_call_for_heat_splits_spells():
    report = make_report(
        [("01:00", 18.0), ("05:00", 19.5), ("05:10", 19.5), ("07:00", 19.5), ("10:00", 21.0)],
        calls=[("00:00", "05:00", "NONE"), ("05:00", "06:00", "LOW"), ("06:00", "next", "NONE")],
    )
    assert find_problems(report, DAY) == []


def test_rise_must_come_after_the_low():
    report = make_report([("08:00", 22.0), ("12:00", 18.0)])
    assert find_problems(report, DAY) == []


def test_points_outside_the_day_are_ignored():
    report = make_report(
        [("23:45", 15.0)],
        calls=[("23:00", "next", "NONE")],
    )
    report["measuredData"]["insideTemperature"]["dataPoints"] = [
        {"timestamp": at("23:00", "2026-11-09"), "value": {"celsius": 15.0}},
        {"timestamp": at("00:10", "2026-11-11"), "value": {"celsius": 25.0}},
    ]
    report["callForHeat"]["dataIntervals"] = [
        {"from": at("22:00", "2026-11-09"), "to": at("01:00", "2026-11-11"), "value": "NONE"},
    ]
    assert find_problems(report, DAY) == []


# --- offline ------------------------------------------------------------------


def test_short_offline_drop_is_ignored():
    report = make_report(
        connected=[("00:00", "10:00", True), ("10:00", "10:59", False), ("10:59", "next", True)]
    )
    assert find_problems(report, DAY) == []


def test_offline_spells_add_up_to_the_hour():
    report = make_report(
        connected=[
            ("00:00", "09:00", True),
            ("09:00", "09:40", False),
            ("09:40", "12:00", True),
            ("12:00", "12:30", False),
            ("12:30", "next", True),
        ]
    )
    found = find_problems(report, DAY)
    assert kinds(found) == ["offline"]
    assert found[0].start == utc(2026, 11, 10, 9, 0)


def test_offline_all_day_without_temperatures():
    report = make_report(connected=[("00:00", "next", False)])
    found = find_problems(report, DAY)
    assert kinds(found) == ["offline"]
    assert found[0].start == utc(2026, 11, 10, 0, 0)


def test_offline_before_the_day_counts_from_midnight():
    report = make_report(connected=[("00:00", "next", False)])
    report["measuredData"]["measuringDeviceConnected"]["dataIntervals"][0]["from"] = at(
        "19:35", "2026-11-09"
    )
    assert find_problems(report, DAY)[0].start == utc(2026, 11, 10, 0, 0)


# --- missing data and day edges -------------------------------------------------


def test_missing_series_give_no_findings():
    assert find_problems({}, DAY) == []
    report = make_report([("08:00", 18.0), ("12:00", 25.0)])
    del report["callForHeat"]
    assert find_problems(report, DAY) == []


def test_summer_time_day_window_and_local_times():
    start, end = day_window(date(2026, 7, 1))
    assert start == utc(2026, 6, 30, 23, 0)
    assert end == utc(2026, 7, 1, 23, 0)
    autumn = day_window(date(2026, 10, 25))
    assert autumn[1] - autumn[0] == timedelta(hours=25)
    spring = day_window(date(2026, 3, 29))
    assert spring[1] - spring[0] == timedelta(hours=23)


def test_fixture_holds_only_what_detection_needs():
    """The repo is public: away/home stripes, weather and the rest must stay out."""
    report = load_fixture()
    assert set(report) <= {
        "zoneType",
        "interval",
        "hoursInDay",
        "measuredData",
        "callForHeat",
        "settings",
    }
    assert set(report["measuredData"]) <= {"insideTemperature", "measuringDeviceConnected"}


@pytest.mark.parametrize(
    "measured", [None, {"insideTemperature": None}, {"insideTemperature": {"dataPoints": None}}]
)
def test_null_series_do_not_crash(measured):
    report = make_report(connected=[("00:00", "next", False)])
    connected = report["measuredData"]["measuringDeviceConnected"]
    report["measuredData"] = measured
    assert find_problems(report, DAY) == []
    if measured is not None:
        report["measuredData"]["measuringDeviceConnected"] = connected
        assert kinds(find_problems(report, DAY)) == ["offline"]


def test_null_values_in_points_and_intervals_are_skipped():
    report = make_report([("08:00", 18.0), ("12:00", 25.0)])
    report["measuredData"]["insideTemperature"]["dataPoints"].append(
        {"timestamp": at("13:00"), "value": None}
    )
    report["callForHeat"] = None
    assert find_problems(report, DAY) == []
