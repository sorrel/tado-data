"""
The commands that record batteries: replaced, make and meter readings.

No test reaches Tado: a fake client stands in, per CLAUDE.md.
"""

import json

import pytest
from click.testing import CliRunner

from commands.battery_record import (
    battery_make_command,
    battery_reading_command,
    battery_replaced_command,
)
from tests.battery_helpers import (
    _seed,
)


def test_replaced_command_saves_the_lifespan(frozen_today, history_file):
    history_file.write_text(
        json.dumps({"devices": {"VA1": {"good_since": "2026-05-01", "low_since": "2026-08-20"}}})
    )

    result = CliRunner().invoke(battery_replaced_command, ["va1"], input="\n\n")

    assert result.exit_code == 0
    assert "111" in result.output
    assert (
        json.loads(history_file.read_text())["devices"]["VA1"]["past_batteries"][0]["days"] == 111
    )


def test_replaced_command_keeps_a_never_low_battery_as_a_minimum(frozen_today, history_file):
    history_file.write_text(
        json.dumps({"devices": {"VA1": {"good_since": "2026-05-01", "low_since": None}}})
    )

    result = CliRunner().invoke(battery_replaced_command, ["va1"], input="\n\n")

    assert result.exit_code == 0
    assert "never gave a low warning" in result.output
    assert "116" in result.output
    saved = json.loads(history_file.read_text())["devices"]["VA1"]["past_batteries"][0]
    assert saved["went_low"] is None and saved["minimum"] is True


def test_replaced_command_twice_in_a_day_changes_nothing(frozen_today, history_file):
    history_file.write_text(
        json.dumps({"devices": {"VA1": {"good_since": "2026-05-01", "low_since": None}}})
    )
    runner = CliRunner()
    runner.invoke(battery_replaced_command, ["va1"], input="\n\n")

    result = runner.invoke(battery_replaced_command, ["va1"], input="\n\n")

    assert "already marked as replaced today" in result.output
    assert len(json.loads(history_file.read_text())["devices"]["VA1"]["past_batteries"]) == 1


def test_replaced_command_refuses_an_unknown_serial(frozen_today, history_file):
    result = CliRunner().invoke(battery_replaced_command, ["VA9"])

    assert result.exit_code != 0
    assert "No battery history for VA9" in result.output


def test_replaced_command_asks_both_makes_when_the_old_one_is_unknown(frozen_today, history_file):
    saved = _seed(history_file, {"good_since": "2026-05-01", "low_since": "2026-08-20"})

    result = CliRunner().invoke(battery_replaced_command, ["va1"], input="Duracell\nEnergizer\n")

    assert result.exit_code == 0, result.output
    assert "Make of the new batteries" in result.output
    assert "Make of the batteries taken out" in result.output
    assert saved()["make"] == "Duracell"
    assert saved()["past_batteries"][0]["make"] == "Energizer"


def test_replaced_command_asks_only_the_new_make_when_the_old_one_is_known(
    frozen_today, history_file
):
    saved = _seed(
        history_file, {"good_since": "2026-05-01", "low_since": None, "make": "Energizer"}
    )

    result = CliRunner().invoke(battery_replaced_command, ["va1"], input="duracell\n")

    assert result.exit_code == 0, result.output
    assert "taken out" not in result.output
    assert "Makes recorded so far: Energizer" in result.output
    assert saved()["make"] == "duracell"
    assert saved()["past_batteries"][0]["make"] == "Energizer"


def test_skipping_the_make_prompts_saves_no_make(frozen_today, history_file):
    saved = _seed(history_file, {"good_since": "2026-05-01", "low_since": None})

    result = CliRunner().invoke(battery_replaced_command, ["va1"], input="\n\n")

    assert result.exit_code == 0, result.output
    assert "make" not in saved()
    assert "make" not in saved()["past_batteries"][0]


def test_replaced_command_takes_the_makes_as_options_without_asking(frozen_today, history_file):
    saved = _seed(history_file, {"good_since": "2026-05-01", "low_since": None})

    result = CliRunner().invoke(
        battery_replaced_command, ["va1", "--make", "Ikea", "--old-make", "Varta"]
    )

    assert result.exit_code == 0, result.output
    assert "Enter to skip" not in result.output
    assert saved()["make"] == "Ikea"
    assert saved()["past_batteries"][0]["make"] == "Varta"


def test_replaced_twice_in_a_day_asks_nothing(frozen_today, history_file):
    _seed(history_file, {"good_since": "2026-08-25", "low_since": None})

    result = CliRunner().invoke(battery_replaced_command, ["va1"])

    assert result.exit_code == 0, result.output
    assert "already marked as replaced today" in result.output
    assert "Enter to skip" not in result.output


def test_make_command_records_the_make_of_the_fitted_set(frozen_today, history_file):
    saved = _seed(history_file, {"good_since": "2026-05-01", "low_since": None})

    result = CliRunner().invoke(battery_make_command, ["va1", "Duracell"])

    assert result.exit_code == 0, result.output
    assert saved()["make"] == "Duracell"


def test_make_command_old_set_corrects_the_set_taken_out(frozen_today, history_file):
    past = {"fitted": "2026-01-01", "went_low": None, "replaced": "2026-05-01", "days": 120,
            "minimum": True, "make": "Duracel"}  # fmt: skip
    saved = _seed(
        history_file, {"good_since": "2026-05-01", "low_since": None, "past_batteries": [past]}
    )

    result = CliRunner().invoke(battery_make_command, ["va1", "Duracell", "--old-set"])

    assert result.exit_code == 0, result.output
    assert "taken out on 2026-05-01" in result.output
    assert saved()["past_batteries"][0]["make"] == "Duracell"


def test_make_command_old_set_without_a_replacement_is_refused(frozen_today, history_file):
    _seed(history_file, {"good_since": "2026-05-01", "low_since": None})

    result = CliRunner().invoke(battery_make_command, ["va1", "Ikea", "--old-set"])

    assert result.exit_code != 0
    assert "no replaced batteries" in result.output


def test_reading_command_saves_a_reading(frozen_today, history_file):
    history_file.write_text(
        json.dumps({"devices": {"VA1": {"good_since": "2026-05-01", "low_since": "2026-08-20"}}})
    )

    result = CliRunner().invoke(battery_reading_command, ["va1", "30", "40", "--note", "left in"])

    assert result.exit_code == 0, result.output
    saved = json.loads(history_file.read_text())["devices"]["VA1"]["meter_readings"]
    assert saved == [{"date": "2026-08-25", "percent": [30, 40], "note": "left in"}]
    assert "30%, 40%" in result.output


def test_reading_command_takes_an_earlier_date(frozen_today, history_file):
    history_file.write_text(
        json.dumps({"devices": {"VA1": {"good_since": "2026-05-01", "low_since": None}}})
    )

    result = CliRunner().invoke(
        battery_reading_command, ["VA1", "90", "90", "--date", "2026-08-20"]
    )

    assert result.exit_code == 0, result.output
    saved = json.loads(history_file.read_text())["devices"]["VA1"]["meter_readings"]
    assert saved[0]["date"] == "2026-08-20"


@pytest.mark.parametrize(
    "args", [["VA1"], ["VA1", "101"], ["VA1", "-1"], ["VA1", "50", "--date", "2026-08-26"]]
)
def test_reading_command_refuses_bad_input(frozen_today, history_file, args):
    history_file.write_text(
        json.dumps({"devices": {"VA1": {"good_since": "2026-05-01", "low_since": None}}})
    )

    result = CliRunner().invoke(battery_reading_command, args)

    assert result.exit_code != 0
    assert "meter_readings" not in history_file.read_text()


def test_reading_command_puts_an_old_set_reading_on_the_batteries_taken_out(
    frozen_today, history_file
):
    old = {
        "fitted": "2026-05-01",
        "went_low": None,
        "replaced": "2026-08-20",
        "days": 111,
        "minimum": True,
    }
    history_file.write_text(
        json.dumps(
            {
                "devices": {
                    "VA1": {"good_since": "2026-08-20", "low_since": None, "past_batteries": [old]}
                }
            }
        )
    )

    result = CliRunner().invoke(battery_reading_command, ["VA1", "50", "50", "--old-set"])

    assert result.exit_code == 0, result.output
    assert "taken out on 2026-08-20" in result.output
    saved = json.loads(history_file.read_text())["devices"]["VA1"]
    assert saved["past_batteries"][0]["meter_readings"] == [
        {"date": "2026-08-20", "percent": [50, 50]}
    ]
    assert "meter_readings" not in saved


def test_reading_command_refuses_an_old_set_reading_with_nothing_taken_out(
    frozen_today, history_file
):
    history_file.write_text(
        json.dumps({"devices": {"VA1": {"good_since": "2026-05-01", "low_since": None}}})
    )

    result = CliRunner().invoke(battery_reading_command, ["VA1", "50", "--old-set"])

    assert result.exit_code != 0
    assert "no replaced batteries" in result.output
    assert "meter_readings" not in history_file.read_text()


def test_reading_command_refuses_an_unknown_device(frozen_today, history_file):
    history_file.write_text(json.dumps({"devices": {}}))

    result = CliRunner().invoke(battery_reading_command, ["VA9", "30"])

    assert result.exit_code != 0
    assert "No battery history for VA9" in result.output


def test_help_explains_how_to_record_the_old_batteries_reading():
    reading_help = CliRunner().invoke(battery_reading_command, ["--help"]).output
    replaced_help = CliRunner().invoke(battery_replaced_command, ["--help"]).output

    assert "tado battery-reading loo 50 50 --old-set" in reading_help
    assert "before battery-replaced" in reading_help
    assert "tado battery-reading loo 50 50 --note" in replaced_help
    assert "--old-set" in replaced_help
