"""
Tests for the battery report's display helpers.

_get_device_zone_map takes a client, but only ever calls get_zones(), so a
small stub stands in for it — no network, per CLAUDE.md.
"""

import json

import click
import pytest
from click.testing import CliRunner

import commands.battery as battery_mod
from commands.battery import AGE_BANDS, _age_colour, _days_since, _format_last, _get_device_zone_map


class FakeClient:
    """Stands in for TadoClient; returns whatever zones it was handed."""

    def __init__(self, zones):
        self._zones = zones

    def get_zones(self):
        return self._zones


# --- _days_since ----------------------------------------------------------


def test_days_since_returns_none_for_no_date(frozen_today):
    assert _days_since(None) is None
    assert _days_since("") is None


def test_days_since_returns_none_for_unparseable_date(frozen_today):
    assert _days_since("not-a-date") is None
    assert _days_since("2026-13-45") is None


def test_days_since_today_is_zero(frozen_today):
    assert _days_since("2026-08-25") == 0


def test_days_since_counts_whole_days(frozen_today):
    assert _days_since("2026-08-15") == 10
    assert _days_since("2025-08-25") == 365


# --- _age_colour ----------------------------------------------------------


@pytest.mark.parametrize(
    "days,expected",
    [
        (0, "bright_green"),
        (99, "bright_green"),
        (100, "bright_cyan"),  # band boundary
        (199, "bright_cyan"),
        (250, "bright_yellow"),
        (300, "bright_magenta"),
        (400, "bright_red"),
    ],
)
def test_age_colour_changes_every_hundred_days(days, expected):
    assert _age_colour(days) == expected


def test_age_colour_clamps_at_the_last_band():
    """Very old batteries stay red rather than running off the end."""
    assert _age_colour(5000) == AGE_BANDS[-1]
    assert _age_colour(100_000) == AGE_BANDS[-1]


# --- _format_last ---------------------------------------------------------


def test_format_last_is_blank_with_no_past_batteries():
    assert click.unstyle(_format_last([])) == " " * 6


def test_format_last_shows_a_measured_lifespan():
    assert click.unstyle(_format_last([{"days": 204, "minimum": False}])) == "  204d"


def test_format_last_marks_a_minimum():
    assert click.unstyle(_format_last([{"days": 210, "minimum": True}])) == " ≥210d"


def test_format_last_uses_the_most_recent_battery():
    past = [{"days": 90, "minimum": False}, {"days": 204, "minimum": False}]

    assert click.unstyle(_format_last(past)) == "  204d"


# --- the report itself ----------------------------------------------------


class FakeReportClient:
    """Stands in for TadoClient for a whole report; no network."""

    def connect(self):
        return True

    def get_devices(self):
        return [{"serialNo": "VA1", "shortSerialNo": "VA1", "deviceType": "VA01", "batteryState": "NORMAL"}]

    def get_zones(self):
        return [{"name": "Lounge", "devices": [{"serialNo": "VA1"}]}]


def test_report_shows_the_last_lifespan_after_a_replacement(frozen_today, history_file, monkeypatch):
    history_file.write_text(json.dumps({"devices": {"VA1": {"good_since": "2026-05-01", "low_since": "2026-08-20"}}}))
    monkeypatch.setattr(battery_mod, "TadoClient", FakeReportClient)

    result = CliRunner().invoke(battery_mod.battery_command)

    assert result.exit_code == 0
    assert "Last" in result.output
    assert "111d" in result.output


# --- average lifespan -----------------------------------------------------


def test_average_leaves_out_unknown_age_batteries():
    """A minimum isn't a real lifespan, so it would drag the average down."""
    lifespans = [
        {"days": 200, "minimum": False},
        {"days": 100, "minimum": False},
        {"days": 999, "minimum": True},
    ]

    assert battery_mod._average_days(lifespans) == 150


@pytest.mark.parametrize("lifespans", [[], [{"days": 206, "minimum": True}]])
def test_average_is_none_without_a_measured_lifespan(lifespans):
    assert battery_mod._average_days(lifespans) is None


# --- the battery-history command ------------------------------------------


def _past(fitted, days, minimum=False):
    return {"fitted": fitted, "went_low": "2026-11-09", "replaced": "2026-11-10", "days": days, "minimum": minimum}


def _seed_history(history_file, past_batteries):
    history_file.write_text(json.dumps({"devices": {
        "VA1": {"good_since": "2026-11-10", "low_since": None, "past_batteries": past_batteries},
    }}))


def test_history_lists_every_past_battery(frozen_today, history_file, monkeypatch):
    _seed_history(history_file, [_past("2026-04-19", 204), _past("2026-04-17", 206, minimum=True)])
    monkeypatch.setattr(battery_mod, "TadoClient", FakeReportClient)

    result = CliRunner().invoke(battery_mod.battery_history_command)

    assert result.exit_code == 0
    assert "Lounge" in result.output
    assert "2026-04-19" in result.output
    assert " 204d" in result.output
    assert "≥206d" in result.output


def test_history_shows_the_average_and_what_it_left_out(frozen_today, history_file, monkeypatch):
    _seed_history(history_file, [
        _past("2026-04-19", 200),
        _past("2026-04-20", 100),
        _past("2026-04-17", 206, minimum=True),
    ])
    monkeypatch.setattr(battery_mod, "TadoClient", FakeReportClient)

    result = CliRunner().invoke(battery_mod.battery_history_command)

    assert "Average: 150d from 2 sets" in result.output
    assert "1 of unknown age not counted" in result.output


def test_history_says_so_when_nothing_has_been_replaced(frozen_today, history_file, monkeypatch):
    history_file.write_text(json.dumps({"devices": {"VA1": {"good_since": "2026-04-17", "low_since": None}}}))
    monkeypatch.setattr(battery_mod, "TadoClient", FakeReportClient)

    result = CliRunner().invoke(battery_mod.battery_history_command)

    assert "No replaced batteries recorded yet." in result.output


def test_history_still_lists_batteries_when_tado_is_unavailable(frozen_today, history_file, monkeypatch):
    """Room names need the API, but the history itself is local."""

    class OfflineClient(FakeReportClient):
        def connect(self):
            return False

    _seed_history(history_file, [_past("2026-04-19", 204)])
    monkeypatch.setattr(battery_mod, "TadoClient", OfflineClient)

    result = CliRunner().invoke(battery_mod.battery_history_command)

    assert result.exit_code == 0
    assert "VA1" in result.output
    assert "Average: 204d from 1 set" in result.output


# --- _get_device_zone_map -------------------------------------------------


def test_maps_serial_numbers_to_zone_names():
    client = FakeClient([
        {"name": "Lounge", "devices": [{"serialNo": "AAA"}, {"serialNo": "BBB"}]},
        {"name": "Kitchen", "devices": [{"serialNo": "CCC"}]},
    ])

    assert _get_device_zone_map(client) == {
        "AAA": "Lounge",
        "BBB": "Lounge",
        "CCC": "Kitchen",
    }


def test_zone_without_a_name_falls_back_to_unknown():
    client = FakeClient([{"devices": [{"serialNo": "AAA"}]}])

    assert _get_device_zone_map(client) == {"AAA": "Unknown"}


def test_devices_without_a_serial_are_skipped():
    client = FakeClient([
        {"name": "Lounge", "devices": [{"serialNo": "AAA"}, {"shortSerialNo": "no-serial"}]},
    ])

    assert _get_device_zone_map(client) == {"AAA": "Lounge"}


def test_zone_with_no_devices_contributes_nothing():
    client = FakeClient([{"name": "Empty room"}])

    assert _get_device_zone_map(client) == {}


@pytest.mark.parametrize("zones", [None, []])
def test_returns_empty_map_when_zones_unavailable(zones):
    """get_zones() returns None when the API call fails."""
    assert _get_device_zone_map(FakeClient(zones)) == {}
