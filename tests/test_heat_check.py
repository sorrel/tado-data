"""
Tests for the heat-check command, its scheduled run and the notifier.

TadoClient is replaced by FakeHeatClient and notify by a recorder, so nothing
reaches Tado and no notification is shown.
"""

import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import pytest
from click.testing import CliRunner

import tado_data.commands.heat_check as hc
import tado_data.core.notify as notify_mod
import tado_data.core.storage as storage_mod
from tado_data.core.auth import LoginNeeded
from tado_data.core.client import RateLimited
from tado_data.core.heat_detect import Offline, Warming
from tado_data.core.heat_store import load_day_report, load_state, save_state
from tado_data.core.storage import load_battery_history

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "dayreport_fault.json").read_text())
FAULT_DAY = date(2026, 11, 10)
ZONES = [
    {"id": 12, "name": "Downstairs Loo", "type": "HEATING", "devices": [{"serialNo": "VA1"}]},
    {"id": 0, "name": "Hot Water", "type": "HOT_WATER"},
    {"id": 3, "name": "Hall", "type": "HEATING", "devices": [{"serialNo": "RU1"}]},
]


def device(serial, kind, battery="NORMAL", online=True):
    return {
        "serialNo": serial,
        "shortSerialNo": serial,
        "deviceType": kind,
        "batteryState": battery,
        "connectionState": {"value": online},
    }


ALL_NORMAL = [
    device("VA1", "VA02"),
    device("RU1", "RU02"),
    {"serialNo": "GW1", "deviceType": "GW03"},
]


def offline_report(day):
    end = day + timedelta(days=1)
    return {
        "measuredData": {
            "measuringDeviceConnected": {
                "dataIntervals": [
                    {"from": f"{day}T00:00:00Z", "to": f"{end}T00:00:00Z", "value": False},
                ]
            }
        }
    }


def fault_day_only(zone_id, day):
    return FIXTURE if (zone_id, day) == (12, FAULT_DAY) else {}


def loo_offline_every_day(zone_id, day):
    return offline_report(day) if zone_id == 12 else {}


class FakeHeatClient:
    """Stands in for TadoClient. `reports(zone_id, day)` decides each day report."""

    reports = staticmethod(fault_day_only)
    devices: ClassVar[list] = ALL_NORMAL
    connect_error = None
    fail_on_day = None
    instances: ClassVar[list] = []

    def __init__(self):
        self.home_id = 42
        self.rate_limit = "RateLimit-Remaining=19000"
        self.interactive = None
        self.report_calls = []
        self.device_calls = 0
        FakeHeatClient.instances.append(self)

    def connect(self, interactive=True):
        self.interactive = interactive
        if self.connect_error:
            raise self.connect_error
        return True

    def get_zones(self, strict=False):
        return ZONES

    def get_devices(self, strict=False):
        self.device_calls += 1
        return self.devices

    def get_day_report(self, zone_id, day):
        self.report_calls.append((zone_id, day))
        if day == self.fail_on_day:
            raise RateLimited("Tado returned 429", status=429)
        return self.reports(zone_id, day)


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(hc, "notify", lambda title, message: messages.append((title, message)))
    return messages


@pytest.fixture
def fake(monkeypatch, heat_store_dir, history_file):
    FakeHeatClient.instances = []
    monkeypatch.setattr(FakeHeatClient, "devices", ALL_NORMAL)
    monkeypatch.setattr(FakeHeatClient, "reports", staticmethod(fault_day_only))
    monkeypatch.setattr(FakeHeatClient, "connect_error", None)
    monkeypatch.setattr(FakeHeatClient, "fail_on_day", None)
    monkeypatch.setattr(hc, "TadoClient", FakeHeatClient)
    return FakeHeatClient


def on(monkeypatch, today):
    """Pin today for the command."""

    class Today(date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr(hc, "date", Today)
    monkeypatch.setattr(storage_mod, "date", Today)  # the battery history's dates


def run(*args):
    return CliRunner().invoke(hc.heat_check_command, list(args))


def report_calls():
    return sum(len(client.report_calls) for client in FakeHeatClient.instances)


# --- which days ---------------------------------------------------------------


def test_days_to_check_first_run_is_yesterday():
    assert hc.days_to_check(date(2026, 8, 25), None) == ([date(2026, 8, 24)], [])


def test_days_to_check_catches_up_oldest_first():
    days, skipped = hc.days_to_check(date(2026, 8, 25), date(2026, 8, 21))
    assert days == [date(2026, 8, 22), date(2026, 8, 23), date(2026, 8, 24)]
    assert skipped == []


def test_days_to_check_skips_beyond_seven_days():
    days, skipped = hc.days_to_check(date(2026, 8, 25), date(2026, 8, 10))
    assert days == [date(2026, 8, 18) + timedelta(days=n) for n in range(7)]
    assert skipped == [date(2026, 8, 11) + timedelta(days=n) for n in range(7)]


def test_days_to_check_nothing_when_up_to_date():
    assert hc.days_to_check(date(2026, 8, 25), date(2026, 8, 24)) == ([], [])


# --- formatting -----------------------------------------------------------------


def test_format_finding_matches_the_spec():
    utc = UTC
    warming = Warming(
        datetime(2026, 11, 10, 10, tzinfo=utc),
        datetime(2026, 11, 10, 18, tzinfo=utc),
        6.62,
        18.56,
        25.18,
    )
    offline = Offline(datetime(2026, 11, 10, 19, 35, 55, tzinfo=utc))
    assert (
        hc.format_finding(warming)
        == "warmed 6.6° (18.6° → 25.2°) between 10:00 and 18:00 with no call for heat"
    )
    assert hc.format_finding(offline) == "offline from 19:35"


def test_format_finding_shows_summer_time():
    finding = Offline(datetime(2026, 7, 1, 18, 35, tzinfo=UTC))
    assert hc.format_finding(finding) == "offline from 19:35"


# --- manual runs ------------------------------------------------------------------


def test_manual_run_prints_findings_and_never_notifies(monkeypatch, fake, sent):
    on(monkeypatch, date(2026, 11, 11))
    result = run()
    assert result.exit_code == 0, result.output
    assert "Downstairs Loo" in result.output
    assert (
        "warmed 6.6° (18.6° → 25.2°) between 10:00 and 18:00 with no call for heat" in result.output
    )
    assert "offline from 19:35" in result.output
    assert sent == []
    assert load_state() == {"last_checked": None, "faults": {}, "battery_checked": None}


def test_manual_run_clean_day(monkeypatch, fake, sent):
    on(monkeypatch, date(2026, 11, 11))
    result = run("--date", "2026-11-09")
    assert result.exit_code == 0, result.output
    assert "No problems on 2026-11-09" in result.output


def test_manual_run_refuses_today(monkeypatch, fake, sent):
    on(monkeypatch, date(2026, 11, 11))
    result = run("--date", "2026-11-11")
    assert result.exit_code != 0
    assert report_calls() == 0


def test_cached_day_makes_no_report_requests(monkeypatch, fake, sent):
    on(monkeypatch, date(2026, 11, 11))
    run()
    first = report_calls()
    assert first == 2  # two heating zones
    run()
    assert report_calls() == first
    assert load_day_report(FAULT_DAY, 12) == FIXTURE


def test_hot_water_zones_are_skipped(monkeypatch, fake, sent):
    on(monkeypatch, date(2026, 11, 11))
    run()
    assert all(zone_id != 0 for client in fake.instances for zone_id, _ in client.report_calls)


# --- scheduled runs --------------------------------------------------------------


def test_scheduled_notifies_the_fault_day(monkeypatch, fake, sent):
    on(monkeypatch, date(2026, 11, 11))
    result = run("--scheduled")
    assert result.exit_code == 0, result.output
    assert sent == [
        ("Tado heat check", "Downstairs Loo warmed with the heating off; Downstairs Loo is offline")
    ]
    assert load_state()["last_checked"] == "2026-11-10"


def test_scheduled_new_fault_notifies_once_then_quiet(monkeypatch, fake, sent):
    monkeypatch.setattr(FakeHeatClient, "reports", staticmethod(loo_offline_every_day))
    on(monkeypatch, date(2026, 11, 11))
    run("--scheduled")
    on(monkeypatch, date(2026, 11, 12))
    run("--scheduled")
    assert sent == [("Tado heat check", "Downstairs Loo is offline")]


def test_scheduled_clean_day_sends_nothing(monkeypatch, fake, sent):
    on(monkeypatch, date(2026, 11, 10))
    result = run("--scheduled")
    assert result.exit_code == 0, result.output
    assert sent == []
    assert load_state()["last_checked"] == "2026-11-09"


def test_scheduled_never_prompts(monkeypatch, fake, sent):
    on(monkeypatch, date(2026, 11, 11))
    run("--scheduled")
    assert fake.instances[0].interactive is False


def test_scheduled_login_needed_notifies_and_exits_1(monkeypatch, fake, sent):
    monkeypatch.setattr(FakeHeatClient, "connect_error", LoginNeeded("no saved login"))
    on(monkeypatch, date(2026, 11, 11))
    result = run("--scheduled")
    assert result.exit_code == 1
    assert sent == [
        ("Tado heat check", "Heat check didn't run: Tado login has expired. Run tado auth.")
    ]


def test_scheduled_rate_limited_keeps_saved_days(monkeypatch, fake, sent):
    monkeypatch.setattr(FakeHeatClient, "reports", staticmethod(loo_offline_every_day))
    monkeypatch.setattr(FakeHeatClient, "fail_on_day", date(2026, 11, 10))
    save_state({"last_checked": "2026-11-08", "faults": {}})
    on(monkeypatch, date(2026, 11, 11))
    result = run("--scheduled")
    assert result.exit_code == 1
    assert load_state()["last_checked"] == "2026-11-09"
    assert load_day_report(date(2026, 11, 9), 12) is not None
    # the fault found before the limit was hit is still notified
    assert sent == [
        (
            "Tado heat check",
            (
                "Tado's daily request limit was reached; the check will carry on tomorrow.; "
                "Downstairs Loo is offline"
            ),
        )
    ]


def test_failed_run_does_not_move_last_checked(monkeypatch, fake, sent):
    monkeypatch.setattr(FakeHeatClient, "fail_on_day", date(2026, 11, 10))
    save_state({"last_checked": "2026-11-09", "faults": {}})
    on(monkeypatch, date(2026, 11, 11))
    run("--scheduled")
    assert load_state()["last_checked"] == "2026-11-09"


def test_scheduled_damaged_state_notifies(monkeypatch, fake, sent, heat_store_dir):
    (heat_store_dir / "heat_check.json").write_text("{")
    on(monkeypatch, date(2026, 11, 11))
    result = run("--scheduled")
    assert result.exit_code == 1
    assert sent == [
        ("Tado heat check", "Heat check didn't run: a saved file is damaged. See the log.")
    ]
    assert (heat_store_dir / "heat_check.json").read_text() == "{"


def test_scheduled_unexpected_error_notifies(monkeypatch, fake, sent):
    def broken(zone_id, day):
        raise KeyError("surprise")

    monkeypatch.setattr(FakeHeatClient, "reports", staticmethod(broken))
    on(monkeypatch, date(2026, 11, 11))
    result = run("--scheduled")
    assert result.exit_code == 1
    assert sent == [("Tado heat check", "Heat check didn't run: unexpected error. See the log.")]


def test_scheduled_with_date_is_a_usage_error(monkeypatch, fake, sent):
    on(monkeypatch, date(2026, 11, 11))
    result = run("--scheduled", "--date", "2026-11-09")
    assert result.exit_code == 2
    assert report_calls() == 0


# --- notifying ------------------------------------------------------------------


def test_notify_passes_text_as_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(
        notify_mod.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs))
    )
    notify_mod.notify("Tado heat check", 'Loo "quoted" & odd')
    args, kwargs = calls[0]
    assert args[0] == "osascript"
    assert args[-2:] == ["Tado heat check", 'Loo "quoted" & odd']
    assert kwargs["check"] is True


def test_notify_raises_notify_error_when_osascript_fails(monkeypatch):
    def fail(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(notify_mod.subprocess, "run", fail)
    with pytest.raises(notify_mod.NotifyError):
        notify_mod.notify("t", "m")


def test_notify_failure_is_reported_on_stderr(monkeypatch, fake):
    def broken(title, message):
        raise notify_mod.NotifyError("osascript not found")

    monkeypatch.setattr(hc, "notify", broken)
    on(monkeypatch, date(2026, 11, 11))
    result = run("--scheduled")
    assert result.exit_code == 1
    assert "Couldn't show the notification" in result.stderr
    assert "Downstairs Loo is offline" in result.stderr
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_scheduled_with_no_heating_zones_is_a_failure(monkeypatch, fake, sent):
    """An empty zone list must not pass as a healthy house."""
    monkeypatch.setattr(FakeHeatClient, "get_zones", lambda self, strict=False: [])
    on(monkeypatch, date(2026, 11, 11))
    result = run("--scheduled")
    assert result.exit_code == 1
    assert sent == [("Tado heat check", "Heat check didn't run: Tado listed no heating zones.")]
    assert load_state()["last_checked"] is None


# --- the daily battery check ----------------------------------------------------


def device_calls():
    return sum(client.device_calls for client in FakeHeatClient.instances)


def battery_run(monkeypatch, today, devices):
    """A scheduled run on TODAY with every day report clean, so only batteries notify."""
    monkeypatch.setattr(FakeHeatClient, "reports", staticmethod(lambda zone_id, day: {}))
    monkeypatch.setattr(FakeHeatClient, "devices", devices)
    on(monkeypatch, today)
    return run("--scheduled")


def test_scheduled_records_battery_states(monkeypatch, fake, sent):
    result = battery_run(monkeypatch, date(2026, 11, 10), ALL_NORMAL)
    assert result.exit_code == 0, result.output
    history = load_battery_history()
    assert set(history) == {"VA1", "RU1"}  # the gateway has no battery
    assert history["VA1"]["good_since"] == "2026-11-10"
    assert load_state()["battery_checked"] == "2026-11-10"
    assert sent == []


def test_batteries_are_checked_once_a_day(monkeypatch, fake, sent):
    battery_run(monkeypatch, date(2026, 11, 10), ALL_NORMAL)
    battery_run(monkeypatch, date(2026, 11, 10), ALL_NORMAL)
    assert device_calls() == 1
    battery_run(monkeypatch, date(2026, 11, 11), ALL_NORMAL)
    assert device_calls() == 2


def test_batteries_checked_when_the_days_are_up_to_date(monkeypatch, fake, sent):
    save_state({"last_checked": "2026-11-09", "faults": {}})
    battery_run(monkeypatch, date(2026, 11, 10), ALL_NORMAL)
    assert report_calls() == 0
    assert device_calls() == 1


def test_going_low_notifies_once(monkeypatch, fake, sent):
    low = [device("VA1", "VA02", "LOW"), device("RU1", "RU02")]
    save_state({"last_checked": "2026-11-09", "faults": {}})
    battery_run(monkeypatch, date(2026, 11, 10), ALL_NORMAL)
    battery_run(monkeypatch, date(2026, 11, 11), low)
    battery_run(monkeypatch, date(2026, 11, 12), low)
    assert [message for _, message in sent] == ["Downstairs Loo valve batteries are low"]
    assert load_battery_history()["VA1"]["low_periods"][-1]["seen"] == "2026-11-12"


def test_back_to_normal_and_dying_notify(monkeypatch, fake, sent):
    low = [device("VA1", "VA02", "LOW"), device("RU1", "RU02")]
    dead = [device("VA1", "VA02", "LOW", online=False), device("RU1", "RU02")]
    save_state({"last_checked": "2026-11-09", "faults": {}})
    battery_run(monkeypatch, date(2026, 11, 10), low)
    battery_run(monkeypatch, date(2026, 11, 11), dead)
    battery_run(monkeypatch, date(2026, 11, 12), low)
    battery_run(monkeypatch, date(2026, 11, 13), ALL_NORMAL)
    assert [message for _, message in sent] == [
        "Downstairs Loo valve batteries are low",
        "Downstairs Loo valve has gone offline with low batteries",
        "Downstairs Loo valve is back online",
        "Downstairs Loo valve batteries are back to normal",
    ]


def test_battery_check_failure_is_retried_later_that_day(monkeypatch, fake, sent):
    def broken(self, strict=False):
        raise RateLimited("Tado returned 429", status=429)

    monkeypatch.setattr(FakeHeatClient, "get_devices", broken)
    save_state({"last_checked": "2026-11-09", "faults": {}})
    result = battery_run(monkeypatch, date(2026, 11, 10), ALL_NORMAL)
    assert result.exit_code == 1
    assert load_state()["battery_checked"] is None
