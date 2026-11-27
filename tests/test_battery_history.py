"""
The battery-history command: past sets, averages, low spells, readings and seasons.

No test reaches Tado: a fake client stands in, per CLAUDE.md.
"""

import json
import re

import click
from click.testing import CliRunner

from commands.battery_history import _on_low, _print_low_periods, battery_history_command
from tests.battery_helpers import (
    FakeReportClient,
    _past,
    _seed,
    _seed_history,
    fake_tado,
)


def test_history_lists_every_past_battery(frozen_today, history_file, monkeypatch):
    _seed_history(history_file, [_past("2026-04-19", 204), _past("2026-04-17", 206, minimum=True)])
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert result.exit_code == 0
    assert "Lounge" in result.output
    assert "2026-04-19" in result.output
    assert " 204d" in result.output
    assert "≥206d" in result.output


def test_history_shows_the_average_and_what_it_left_out(frozen_today, history_file, monkeypatch):
    _seed_history(
        history_file,
        [
            _past("2026-04-19", 200),
            _past("2026-04-20", 100),
            _past("2026-04-17", 206, minimum=True),
        ],
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "Average: 150d from 2 sets" in result.output
    assert "1 of unknown age not counted" in result.output


def test_history_shows_each_devices_own_average(frozen_today, history_file, monkeypatch):
    _seed_history(
        history_file,
        [
            _past("2026-04-19", 200),
            _past("2026-04-20", 100),
            _past("2026-04-17", 206, minimum=True),
        ],
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "Average by device" in result.output
    by_device = result.output.split("Average by device")[1]
    assert "Lounge" in by_device
    assert "150d ×2" in by_device


def test_history_has_no_device_averages_until_a_set_is_measured(
    frozen_today, history_file, monkeypatch
):
    _seed_history(history_file, [_past("2026-04-17", 206, minimum=True)])
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "Average by device" not in result.output


def test_history_says_so_when_nothing_has_been_replaced(frozen_today, history_file, monkeypatch):
    history_file.write_text(
        json.dumps({"devices": {"VA1": {"good_since": "2026-04-17", "low_since": None}}})
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "No replaced batteries recorded yet." in result.output


def test_history_still_lists_batteries_when_tado_is_unavailable(
    frozen_today, history_file, monkeypatch
):
    """Room names need the API, but the history itself is local."""

    class OfflineClient(FakeReportClient):
        def connect(self):
            return False

    _seed_history(history_file, [_past("2026-04-19", 204)])
    fake_tado(monkeypatch, OfflineClient)

    result = CliRunner().invoke(battery_history_command)

    assert result.exit_code == 0
    assert "VA1" in result.output
    assert "Average: 204d from 1 set" in result.output


def test_on_low_counts_to_the_day_it_died():
    battery = {"went_low": "2026-11-09", "died": "2026-11-15", "replaced": "2026-11-20"}

    assert _on_low(battery) == {"days": 6, "minimum": False}


def test_on_low_is_a_minimum_when_replaced_before_it_died():
    battery = {"went_low": "2026-11-09", "replaced": "2026-11-20"}

    assert _on_low(battery) == {"days": 11, "minimum": True}


def test_history_shows_time_on_low_and_its_average(frozen_today, history_file, monkeypatch):
    _seed_history(
        history_file,
        [
            {**_past("2026-04-19", 204), "died": "2026-11-10"},  # 1 day on low, then died
            _past("2026-04-20", 203),  # replaced after 1 day, still going
        ],
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "On low" in result.output
    assert "≥1d" in result.output
    assert "Average on low: 1d from 1 set" in result.output


def test_history_has_no_low_average_until_one_has_died(frozen_today, history_file, monkeypatch):
    _seed_history(history_file, [_past("2026-04-19", 204)])
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "Average on low" not in result.output


def test_history_lists_low_spells_before_any_replacement(frozen_today, history_file, monkeypatch):
    history_file.write_text(
        json.dumps(
            {
                "devices": {
                    "VA1": {
                        "good_since": "2026-05-01",
                        "low_since": "2026-08-20",
                        "low_periods": [
                            {"from": "2026-08-20", "to": "2026-08-21"},
                            {"from": "2026-08-24", "to": None},
                        ],
                    }
                }
            }
        )
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "Low warnings" in result.output
    assert "2026-08-21" in result.output
    assert "still low" in result.output
    assert "No replaced batteries" not in result.output


def test_history_keeps_showing_low_spells_of_replaced_batteries(
    frozen_today, history_file, monkeypatch
):
    spell = {"from": "2026-07-01", "to": "2026-07-02"}
    _seed_history(history_file, [{**_past("2026-04-19", 204), "low_periods": [spell]}])
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "2026-07-02" in result.output


def test_on_low_is_none_for_a_battery_that_never_went_low():
    battery = {"went_low": None, "replaced": "2026-11-12"}

    assert _on_low(battery) is None


def test_history_shows_a_never_low_battery(frozen_today, history_file, monkeypatch):
    history_file.write_text(
        json.dumps(
            {
                "devices": {
                    "VA1": {
                        "good_since": "2026-08-25",
                        "low_since": None,
                        "past_batteries": [
                            {
                                "fitted": "2026-05-01",
                                "went_low": None,
                                "replaced": "2026-08-25",
                                "days": 116,
                                "minimum": True,
                            },
                        ],
                    }
                }
            }
        )
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert result.exit_code == 0, result.output
    assert "never" in result.output
    assert "≥116d" in result.output
    assert "Average on low" not in result.output


def test_history_shows_each_set_s_make_and_the_average_by_make(
    frozen_today, history_file, monkeypatch
):
    def past(fitted, went_low, days, make):
        return {"fitted": fitted, "went_low": went_low, "replaced": went_low,
                "days": days, "minimum": False, "make": make}  # fmt: skip

    _seed(
        history_file,
        {
            "good_since": "2026-08-25",
            "low_since": None,
            "past_batteries": [
                past("2025-01-01", "2025-07-20", 200, "Duracell"),
                past("2025-07-20", "2026-02-25", 220, "Duracell"),
                past("2026-02-25", "2026-08-25", 181, "Ikea"),
            ],
        },
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert result.exit_code == 0, result.output
    assert "Average by make" in result.output
    assert re.search(r"Duracell\s+210d ×2", click.unstyle(result.output))
    assert re.search(r"Ikea\s+181d ×1", click.unstyle(result.output))


def test_history_lists_meter_readings_now_and_from_replaced_batteries(
    frozen_today, history_file, monkeypatch
):
    history_file.write_text(
        json.dumps(
            {
                "devices": {
                    "VA1": {
                        "good_since": "2026-05-01",
                        "low_since": None,
                        "meter_readings": [
                            {"date": "2026-08-24", "percent": [30, 40], "note": "left in"}
                        ],
                        "past_batteries": [
                            {
                                **_past("2026-04-19", 204),
                                "meter_readings": [{"date": "2026-07-01", "percent": [90, 90]}],
                            }
                        ],
                    }
                }
            }
        )
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "Meter readings" in result.output
    assert "30%, 40%" in result.output
    assert "left in" in result.output
    assert "90%, 90%" in result.output


def test_history_says_whether_each_read_set_is_still_fitted(
    frozen_today, history_file, monkeypatch
):
    """A note written at the time ("left in for now") goes stale once the set is
    replaced, so each reading shows what has become of its batteries since."""
    history_file.write_text(
        json.dumps(
            {
                "devices": {
                    "VA1": {
                        "good_since": "2026-11-10",
                        "low_since": None,
                        "meter_readings": [{"date": "2026-11-12", "percent": [80, 80]}],
                        "past_batteries": [
                            {
                                **_past("2026-04-19", 204),
                                "meter_readings": [
                                    {
                                        "date": "2026-11-09",
                                        "percent": [30, 40],
                                        "note": "left in for now",
                                    }
                                ],
                            }
                        ],
                    }
                }
            }
        )
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    lines = result.output.splitlines()
    old = next(line for line in lines if "30%, 40%" in line)
    new = next(line for line in lines if "80%, 80%" in line)
    assert "out 2026-11-10" in old
    assert "still in" in new
    assert "Batteries" in result.output


def test_history_shows_meter_readings_on_their_own(frozen_today, history_file, monkeypatch):
    history_file.write_text(
        json.dumps(
            {
                "devices": {
                    "VA1": {
                        "good_since": "2026-05-01",
                        "low_since": None,
                        "meter_readings": [{"date": "2026-08-24", "percent": [70]}],
                    }
                }
            }
        )
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "70%" in result.output
    assert "No replaced batteries" not in result.output


def test_low_warnings_list_shows_when_each_spell_started_and_last_day_seen_low(capsys):
    spells = [
        ("VA0000000001", {"from": "2026-08-20", "to": "2026-08-22", "seen": "2026-08-21"}),
        ("VA0000000001", {"from": "2026-08-24", "to": None}),
    ]

    _print_low_periods(spells, {"VA0000000001": "Hall"})

    lines = click.unstyle(capsys.readouterr().out).splitlines()
    assert "Last low" in lines[1]
    assert "2026-08-20  2026-08-21  2026-08-22" in lines[3]
    assert "2026-08-24  2026-08-24  still low" in lines[4]


def _season_section(output):
    """The lines of the season chart, from its rule to the blank line after it."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if "Average by season fitted" in line)
    rows = []
    for line in lines[start + 3 :]:
        if not line.strip():
            break
        rows.append(line)
    return rows


def test_season_chart_is_left_out_with_no_measured_sets(frozen_today, history_file, monkeypatch):
    _seed_history(history_file, [_past("2026-04-17", 209, minimum=True)])
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert result.exit_code == 0
    assert "Average by season fitted" not in result.output


def test_season_chart_shows_every_season_and_lines_up(frozen_today, history_file, monkeypatch):
    _seed_history(
        history_file,
        [_past("2027-10-01", 150), _past("2027-11-20", 170), _past("2027-07-01", 230)],
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    rows = _season_section(result.output)
    assert [row.split()[0] for row in rows[:4]] == ["Spring", "Summer", "Autumn", "Winter"]
    assert "█" * 30 in rows[1] and "230d ×1" in rows[1]
    assert "160d ×2" in rows[2] and "150–170d" in rows[2]
    assert "none yet" in rows[0] and "none yet" in rows[3]
    assert rows[1].index("d ×") == rows[2].index("d ×")
    assert rows[0].index("none yet") == rows[3].index("none yet")
    assert "read it as a hint" in result.output


def test_season_chart_says_what_it_left_out(frozen_today, history_file, monkeypatch):
    _seed_history(
        history_file,
        [_past("2027-10-01", 150), _past("2026-04-17", 209, minimum=True)],
    )
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "1 set not counted: unknown age, or taken out before they warned." in result.output


def test_season_chart_drops_the_hint_with_three_sets_everywhere(
    frozen_today, history_file, monkeypatch
):
    fitted = ["2027-04-01", "2027-07-01", "2027-10-01", "2027-12-01"]
    _seed_history(history_file, [_past(day, 200) for day in fitted for _ in range(3)])
    fake_tado(monkeypatch, FakeReportClient)

    result = CliRunner().invoke(battery_history_command)

    assert "Average by season fitted" in result.output
    assert "read it as a hint" not in result.output


def test_history_svg_writes_the_file(frozen_today, history_file, monkeypatch, tmp_path):
    _seed_history(history_file, [_past("2027-10-01", 150)])
    fake_tado(monkeypatch, FakeReportClient)
    target = tmp_path / "seasons.svg"

    result = CliRunner().invoke(battery_history_command, ["--svg", str(target)])

    assert result.exit_code == 0
    assert target.read_text(encoding="utf-8").startswith("<svg")
    assert "Season chart saved to" in result.output and "seasons.svg" in result.output


def test_history_svg_writes_nothing_without_a_measured_set(
    frozen_today, history_file, monkeypatch, tmp_path
):
    _seed_history(history_file, [_past("2026-04-17", 209, minimum=True)])
    fake_tado(monkeypatch, FakeReportClient)
    target = tmp_path / "seasons.svg"

    result = CliRunner().invoke(battery_history_command, ["--svg", str(target)])

    assert result.exit_code == 0
    assert not target.exists()
    assert "no measured sets" in result.output.lower()
    assert "Replaced batteries" in result.output


def test_history_svg_reports_a_path_it_cannot_write(
    frozen_today, history_file, monkeypatch, tmp_path
):
    _seed_history(history_file, [_past("2027-10-01", 150)])
    fake_tado(monkeypatch, FakeReportClient)
    target = tmp_path / "no-such-folder" / "seasons.svg"

    result = CliRunner().invoke(battery_history_command, ["--svg", str(target)])

    assert result.exit_code == 1
    assert "Couldn't save the season chart" in result.output
    assert not isinstance(result.exception, OSError)
