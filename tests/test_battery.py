"""
Tests for the battery report's display helpers.

_get_device_zone_map takes a client, but only ever calls get_zones(), so a
small stub stands in for it — no network, per CLAUDE.md.
"""

import pytest

from commands.battery import AGE_BANDS, _age_colour, _days_since, _get_device_zone_map


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
