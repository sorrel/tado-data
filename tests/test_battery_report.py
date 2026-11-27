"""
The battery report: its table, ages and low warnings.

No test reaches Tado: a fake client stands in, per CLAUDE.md.
"""

import json

import click
from click.testing import CliRunner

from tado_data.commands.battery import _days_since, _format_lows, battery_command
from tests.battery_helpers import (
    FakeReportClient,
    fake_tado,
)


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


def test_report_shows_the_last_lifespan_after_a_replacement(
    frozen_today, history_file, monkeypatch
):
    history_file.write_text(
        json.dumps(
            {
                "devices": {
                    "VA1": {
                        "good_since": "2026-08-20",
                        "low_since": None,
                        "past_batteries": [{"days": 111, "minimum": False}],
                    }
                }
            }
        )
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_command)

    assert result.exit_code == 0
    assert "Last" in result.output
    assert "111d" in result.output
    assert "Average" in result.output
    assert "111d ×1" in result.output


def test_report_shows_the_make_of_the_batteries_now_fitted(frozen_today, history_file, monkeypatch):
    history_file.write_text(
        json.dumps(
            {
                "devices": {
                    "VA1": {
                        "good_since": "2026-08-20",
                        "low_since": None,
                        "make": "Duracell",
                        "past_batteries": [{"days": 111, "minimum": False, "make": "Ikea"}],
                    }
                }
            }
        )
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_command)

    assert result.exit_code == 0
    header, _, row = click.unstyle(result.output).strip("\n").splitlines()[:3]
    assert header.rstrip().endswith("Make")
    assert row.rstrip().endswith("Duracell")
    assert "Ikea" not in result.output  # a set already taken out isn't the one fitted


def test_report_leaves_the_make_blank_when_none_is_recorded(
    frozen_today, history_file, monkeypatch
):
    history_file.write_text(
        json.dumps({"devices": {"VA1": {"good_since": "2026-08-20", "low_since": None}}})
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_command)

    assert result.exit_code == 0
    row = click.unstyle(result.output).strip("\n").splitlines()[2]
    assert row.rstrip().endswith("Yes") or row.rstrip().endswith("No")


TWO_SPELLS = [
    {"from": "2026-08-20", "to": "2026-08-21", "seen": "2026-08-20"},
    {"from": "2026-08-24", "to": None, "seen": "2026-08-25"},
]


def test_format_lows_shows_first_day_low_latest_day_low_and_count():
    assert click.unstyle(_format_lows(TWO_SPELLS, is_low=True)) == "2026-08-20  2026-08-25     2"


def test_format_lows_falls_back_to_the_start_of_a_spell_saved_without_seen():
    spells = [{"from": "2026-08-20", "to": None}]

    assert click.unstyle(_format_lows(spells, is_low=True)).startswith("2026-08-20  2026-08-20")


def test_format_lows_is_blank_for_a_device_never_low():
    assert click.unstyle(_format_lows([], is_low=False)) == " " * 28


def test_format_lows_is_red_only_while_the_device_is_low():
    closed = [{"from": "2026-08-20", "to": "2026-08-21"}]

    assert "\x1b[31m" in _format_lows(closed, is_low=True)
    assert "\x1b[" not in _format_lows(closed, is_low=False)


def test_report_shows_low_history_for_a_device_now_normal(frozen_today, history_file, monkeypatch):
    history_file.write_text(
        json.dumps(
            {
                "devices": {
                    "VA1": {
                        "good_since": "2026-05-01",
                        "low_since": "2026-08-20",
                        "low_periods": [
                            {"from": "2026-08-20", "to": "2026-08-21"},
                            {"from": "2026-08-24", "to": "2026-08-24"},
                        ],
                    }
                }
            }
        )
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_command)

    assert result.exit_code == 0
    assert "First low" in result.output
    assert "Latest low" in result.output
    assert "Low since" not in result.output
    assert "2026-08-20  2026-08-24     2" in result.output


def test_report_records_a_low_device_that_has_gone_offline(frozen_today, history_file, monkeypatch):
    class DeadDeviceClient(FakeReportClient):
        def get_devices(self):
            return [
                {
                    "serialNo": "VA1",
                    "shortSerialNo": "VA1",
                    "deviceType": "VA01",
                    "batteryState": "LOW",
                    "connectionState": {"value": False},
                }
            ]

    history_file.write_text(
        json.dumps({"devices": {"VA1": {"good_since": "2026-05-01", "low_since": "2026-08-20"}}})
    )
    fake_tado(monkeypatch, DeadDeviceClient)

    CliRunner().invoke(battery_command)

    assert json.loads(history_file.read_text())["devices"]["VA1"]["died"] == "2026-08-25"


def test_damaged_history_stops_the_report_with_a_clear_message(
    frozen_today, history_file, monkeypatch
):
    history_file.write_text("{ not json at all")
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_command)

    assert result.exit_code != 0
    assert "damaged" in result.output
    assert isinstance(result.exception, SystemExit)  # a clean exit, not a traceback
