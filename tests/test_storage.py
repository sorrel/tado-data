"""
Tests for battery history storage.

The point of update_battery_history is that good_since and low_since are
tracked independently, so a battery going flat doesn't erase the record of
how long it lasted. Most of what follows pins down that behaviour.
"""

import json

import pytest

from core.storage import (
    AlreadyReplacedToday,
    BatteryHistoryError,
    NoOldBatteries,
    _save_json,
    add_meter_reading,
    load_battery_history,
    mark_battery_replaced,
    update_battery_history,
)

SERIAL = "VA1234567890"


def _write(path, devices):
    """Seed the history file directly, as a previous run would have left it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"devices": devices}))


# --- first sighting of a device ------------------------------------------


def test_new_normal_device_records_good_since_today(frozen_today, history_file):
    history = update_battery_history({SERIAL: "NORMAL"})

    assert history[SERIAL] == {"good_since": "2026-08-25", "low_since": None}


def test_new_low_device_records_low_since_today(frozen_today, history_file):
    history = update_battery_history({SERIAL: "LOW"})

    assert history[SERIAL]["good_since"] is None
    assert history[SERIAL]["low_since"] == "2026-08-25"


# --- state transitions ----------------------------------------------------


def test_normal_to_low_preserves_good_since(frozen_today, history_file):
    """The whole point: we keep how long the battery lasted before it died."""
    _write(history_file, {SERIAL: {"good_since": "2025-01-10", "low_since": None}})

    history = update_battery_history({SERIAL: "LOW"})

    assert history[SERIAL]["good_since"] == "2025-01-10"  # untouched
    assert history[SERIAL]["low_since"] == "2026-08-25"


def test_going_back_to_normal_is_not_a_replacement(frozen_today, history_file):
    """Only the user can say a battery was replaced; the same ones may have gone back in."""
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20"}})

    history = update_battery_history({SERIAL: "NORMAL"})

    assert history[SERIAL]["good_since"] == "2026-05-01"
    assert history[SERIAL]["low_since"] == "2026-08-20"


def test_normal_stays_normal_does_not_bump_good_since(frozen_today, history_file):
    """A routine check-in must not restart the clock."""
    _write(history_file, {SERIAL: {"good_since": "2025-01-10", "low_since": None}})

    history = update_battery_history({SERIAL: "NORMAL"})

    assert history[SERIAL]["good_since"] == "2025-01-10"


def test_low_stays_low_does_not_bump_low_since(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2025-01-10", "low_since": "2026-06-01"}})

    history = update_battery_history({SERIAL: "LOW"})

    assert history[SERIAL]["low_since"] == "2026-06-01"


# --- lifespans of replaced batteries --------------------------------------


def test_replacing_a_low_battery_keeps_its_lifespan(frozen_today, history_file):
    """Days run from fitting to the first low warning, not to the swap."""
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20"}})

    mark_battery_replaced(SERIAL)
    history = load_battery_history()

    assert history[SERIAL]["past_batteries"] == [
        {
            "fitted": "2026-05-01",
            "went_low": "2026-08-20",
            "replaced": "2026-08-25",
            "days": 111,
            "minimum": False,
        }
    ]


def test_battery_already_fitted_when_tracking_began_is_a_minimum(frozen_today, history_file):
    """We never saw these go in, so the true lifespan is longer than recorded."""
    _write(history_file, {SERIAL: {"good_since": "2026-04-17", "low_since": "2026-08-20"}})

    mark_battery_replaced(SERIAL)
    history = load_battery_history()

    assert history[SERIAL]["past_batteries"][0]["minimum"] is True


def test_new_lifespan_is_added_after_earlier_ones(frozen_today, history_file):
    earlier = {
        "fitted": "2026-05-01",
        "went_low": "2026-06-01",
        "replaced": "2026-06-02",
        "days": 31,
        "minimum": False,
    }
    _write(
        history_file,
        {
            SERIAL: {
                "good_since": "2026-06-02",
                "low_since": "2026-08-20",
                "past_batteries": [earlier],
            }
        },
    )

    mark_battery_replaced(SERIAL)
    history = load_battery_history()

    past = history[SERIAL]["past_batteries"]
    assert past[0] == earlier
    assert past[1]["fitted"] == "2026-06-02"
    assert len(past) == 2


def test_lifespan_is_recorded_only_once(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20"}})

    mark_battery_replaced(SERIAL)
    with pytest.raises(AlreadyReplacedToday):
        mark_battery_replaced(SERIAL)
    history = load_battery_history()

    assert len(history[SERIAL]["past_batteries"]) == 1


def test_past_batteries_survive_going_low(frozen_today, history_file):
    past = [
        {
            "fitted": "2026-05-01",
            "went_low": "2026-06-01",
            "replaced": "2026-06-02",
            "days": 31,
            "minimum": False,
        }
    ]
    _write(
        history_file,
        {SERIAL: {"good_since": "2026-06-02", "low_since": None, "past_batteries": past}},
    )

    history = update_battery_history({SERIAL: "LOW"})

    assert history[SERIAL]["past_batteries"] == past


def test_past_batteries_are_written_to_disk(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20"}})

    mark_battery_replaced(SERIAL)

    assert load_battery_history()[SERIAL]["past_batteries"][0]["days"] == 111


def test_no_lifespan_without_a_fitted_date(frozen_today, history_file):
    """First seen already LOW: there is nothing to measure from."""
    _write(history_file, {SERIAL: {"good_since": None, "low_since": "2026-08-20"}})

    mark_battery_replaced(SERIAL)
    history = load_battery_history()

    assert "past_batteries" not in history[SERIAL]


def test_no_lifespan_from_an_unparseable_date(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "not-a-date", "low_since": "2026-08-20"}})

    mark_battery_replaced(SERIAL)
    history = load_battery_history()

    assert "past_batteries" not in history[SERIAL]
    assert history[SERIAL]["good_since"] == "2026-08-25"


# --- batteries dying after going low ---------------------------------------


def test_low_device_going_offline_records_when_it_died(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20"}})

    history = update_battery_history({SERIAL: "LOW"}, disconnected={SERIAL})

    assert history[SERIAL]["died"] == "2026-08-25"


def test_first_date_seen_dead_is_kept(frozen_today, history_file):
    _write(
        history_file,
        {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20", "died": "2026-08-22"}},
    )

    history = update_battery_history({SERIAL: "LOW"}, disconnected={SERIAL})

    assert history[SERIAL]["died"] == "2026-08-22"


def test_low_device_coming_back_online_was_not_dead(frozen_today, history_file):
    """A brief network drop mustn't count as the battery dying."""
    _write(
        history_file,
        {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20", "died": "2026-08-22"}},
    )

    history = update_battery_history({SERIAL: "LOW"})

    assert "died" not in history[SERIAL]


def test_normal_device_going_offline_is_not_dead(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": None}})

    history = update_battery_history({SERIAL: "NORMAL"}, disconnected={SERIAL})

    assert "died" not in history[SERIAL]


def test_replacing_a_dead_battery_keeps_when_it_died(frozen_today, history_file):
    _write(
        history_file,
        {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20", "died": "2026-08-22"}},
    )

    mark_battery_replaced(SERIAL)
    history = load_battery_history()

    assert history[SERIAL]["past_batteries"][0]["died"] == "2026-08-22"
    assert "died" not in history[SERIAL]


# --- marking a battery as replaced ----------------------------------------


def test_marking_replaced_restarts_the_clock(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20"}})

    mark_battery_replaced(SERIAL)

    entry = load_battery_history()[SERIAL]
    assert entry["good_since"] == "2026-08-25"
    assert entry["low_since"] is None


def test_replacing_a_battery_that_never_went_low_keeps_its_time_in_as_a_minimum(
    frozen_today, history_file
):
    # Changed while still NORMAL (VA1859608064, November 2026): how long it
    # would have lasted to a low warning is unknown, but it is at least this.
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": None}})

    retired = mark_battery_replaced(SERIAL)

    assert retired == {
        "fitted": "2026-05-01",
        "went_low": None,
        "replaced": "2026-08-25",
        "days": 116,
        "minimum": True,
    }
    entry = load_battery_history()[SERIAL]
    assert entry == {"good_since": "2026-08-25", "low_since": None, "past_batteries": [retired]}


def test_replacing_a_never_low_battery_keeps_its_meter_readings(frozen_today, history_file):
    reading = {"date": "2026-08-24", "percent": [50, 50]}
    _write(
        history_file,
        {SERIAL: {"good_since": "2026-05-01", "low_since": None, "meter_readings": [reading]}},
    )

    retired = mark_battery_replaced(SERIAL)

    assert retired["meter_readings"] == [reading]


def test_marking_an_unknown_device_is_refused(frozen_today, history_file):
    with pytest.raises(KeyError):
        mark_battery_replaced(SERIAL)


def test_low_reading_on_the_day_of_fitting_is_ignored(frozen_today, history_file):
    """Tado can still report the old state just after a swap."""
    _write(history_file, {SERIAL: {"good_since": "2026-08-25", "low_since": None}})

    history = update_battery_history({SERIAL: "LOW"})

    assert history[SERIAL]["low_since"] is None


# --- the record of low spells ----------------------------------------------


def test_going_back_to_normal_keeps_the_last_day_seen_low(frozen_today, history_file):
    spell = {"from": "2026-08-20", "to": None, "seen": "2026-08-23"}
    _write(
        history_file,
        {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20", "low_periods": [spell]}},
    )

    history = update_battery_history({SERIAL: "NORMAL"})

    assert history[SERIAL]["low_periods"] == [{**spell, "to": "2026-08-25"}]


def test_going_low_opens_a_low_spell(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": None}})

    history = update_battery_history({SERIAL: "LOW"})

    assert history[SERIAL]["low_periods"] == [
        {"from": "2026-08-25", "to": None, "seen": "2026-08-25"}
    ]


def test_staying_low_keeps_one_spell(frozen_today, history_file):
    spell = {"from": "2026-08-20", "to": None}
    _write(
        history_file,
        {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20", "low_periods": [spell]}},
    )

    history = update_battery_history({SERIAL: "LOW"})

    assert history[SERIAL]["low_periods"] == [{**spell, "seen": "2026-08-25"}]


def test_going_back_to_normal_closes_the_spell(frozen_today, history_file):
    _write(
        history_file,
        {
            SERIAL: {
                "good_since": "2026-05-01",
                "low_since": "2026-08-20",
                "low_periods": [{"from": "2026-08-20", "to": None}],
            }
        },
    )

    history = update_battery_history({SERIAL: "NORMAL"})

    assert history[SERIAL]["low_periods"] == [{"from": "2026-08-20", "to": "2026-08-25"}]


def test_low_date_saved_before_spells_existed_is_kept(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20"}})

    history = update_battery_history({SERIAL: "NORMAL"})

    assert history[SERIAL]["low_periods"] == [{"from": "2026-08-20", "to": "2026-08-25"}]


def test_going_low_again_adds_a_second_spell(frozen_today, history_file):
    first = {"from": "2026-08-20", "to": "2026-08-21"}
    _write(
        history_file,
        {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20", "low_periods": [first]}},
    )

    history = update_battery_history({SERIAL: "LOW"})

    assert history[SERIAL]["low_periods"] == [
        first,
        {"from": "2026-08-25", "to": None, "seen": "2026-08-25"},
    ]
    assert history[SERIAL]["low_since"] == "2026-08-20"  # still the first warning


def test_replacing_a_battery_keeps_its_low_spells(frozen_today, history_file):
    spells = [{"from": "2026-08-20", "to": "2026-08-21"}]
    _write(
        history_file,
        {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20", "low_periods": spells}},
    )

    mark_battery_replaced(SERIAL)

    entry = load_battery_history()[SERIAL]
    assert entry["past_batteries"][0]["low_periods"] == spells
    assert "low_periods" not in entry


# --- persistence ----------------------------------------------------------


def test_history_is_written_to_disk_and_reloads(frozen_today, history_file):
    update_battery_history({SERIAL: "NORMAL"})

    assert history_file.exists()
    assert load_battery_history() == {SERIAL: {"good_since": "2026-08-25", "low_since": None}}


def test_multiple_devices_tracked_independently(frozen_today, history_file):
    history = update_battery_history({"AAA": "NORMAL", "BBB": "LOW"})

    assert history["AAA"] == {"good_since": "2026-08-25", "low_since": None}
    assert history["BBB"]["low_since"] == "2026-08-25"


# --- legacy format migration ---------------------------------------------


def test_migrates_legacy_normal_entry(frozen_today, history_file):
    """Old format was a single {state, since} pair."""
    _write(history_file, {SERIAL: {"state": "NORMAL", "since": "2025-03-01"}})

    assert load_battery_history()[SERIAL] == {
        "good_since": "2025-03-01",
        "low_since": None,
    }


def test_migrates_legacy_low_entry(frozen_today, history_file):
    _write(history_file, {SERIAL: {"state": "LOW", "since": "2025-03-01"}})

    assert load_battery_history()[SERIAL] == {
        "good_since": None,
        "low_since": "2025-03-01",
    }


# --- degenerate files -----------------------------------------------------


def test_missing_file_returns_empty_history(frozen_today, history_file):
    assert not history_file.exists()
    assert load_battery_history() == {}


@pytest.mark.parametrize("damaged", [b"", b'{"devices": {"VA12', b"\xff\xfe not text"])
def test_damaged_file_is_refused_and_left_alone(frozen_today, history_file, damaged):
    """Treating it as empty would overwrite the real history on the next save."""
    history_file.write_bytes(damaged)

    with pytest.raises(BatteryHistoryError):
        update_battery_history({SERIAL: "NORMAL"})

    assert history_file.read_bytes() == damaged


def test_marking_replaced_is_refused_on_a_damaged_file(frozen_today, history_file):
    history_file.write_text("{ not json at all")

    with pytest.raises(BatteryHistoryError):
        mark_battery_replaced(SERIAL)


# --- saving safely ---------------------------------------------------------


def test_interrupted_save_leaves_the_file_intact(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": None}})
    before = history_file.read_text()

    # json.dump writes as it goes, so this fails part-way through the save
    with pytest.raises(TypeError):
        _save_json(str(history_file), {"devices": {SERIAL: object()}})

    assert history_file.read_text() == before


def test_a_change_keeps_the_previous_version_as_a_backup(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": None}})
    before = history_file.read_text()

    update_battery_history({SERIAL: "LOW"})

    assert history_file.read_text() != before
    assert (history_file.parent / "battery_history.json.bak").read_text() == before


def test_a_run_with_no_change_leaves_the_backup_alone(frozen_today, history_file):
    """Otherwise the backup would soon just be a copy of the current file."""
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": None}})
    backup = history_file.parent / "battery_history.json.bak"
    backup.write_text("the previous version")

    update_battery_history({SERIAL: "NORMAL"})

    assert backup.read_text() == "the previous version"


def test_first_ever_save_has_nothing_to_back_up(frozen_today, history_file):
    update_battery_history({SERIAL: "NORMAL"})

    assert history_file.exists()
    assert not (history_file.parent / "battery_history.json.bak").exists()


# --- meter readings -------------------------------------------------------


def test_a_meter_reading_is_saved_against_the_batteries_now_fitted(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": "2026-08-20"}})

    reading, _ = add_meter_reading(SERIAL, [30, 40], note="left in")

    assert reading == {"date": "2026-08-25", "percent": [30, 40], "note": "left in"}
    assert load_battery_history()[SERIAL]["meter_readings"] == [reading]


def test_a_meter_reading_can_be_backdated_and_needs_no_note(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": None}})

    reading, _ = add_meter_reading(SERIAL, [90, 90], on="2026-08-20")

    assert reading == {"date": "2026-08-20", "percent": [90, 90]}


def test_meter_readings_are_kept_in_date_order(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": None}})

    add_meter_reading(SERIAL, [50, 50])
    add_meter_reading(SERIAL, [90, 90], on="2026-08-01")

    dates = [r["date"] for r in load_battery_history()[SERIAL]["meter_readings"]]
    assert dates == ["2026-08-01", "2026-08-25"]


def test_a_meter_reading_for_an_unknown_device_is_refused(frozen_today, history_file):
    _write(history_file, {})

    with pytest.raises(KeyError):
        add_meter_reading(SERIAL, [30, 40])


def test_meter_readings_survive_a_battery_report(frozen_today, history_file):
    """The report rebuilds each entry, so it must carry the readings across."""
    readings = [{"date": "2026-08-20", "percent": [30, 40]}]
    _write(
        history_file,
        {
            SERIAL: {
                "good_since": "2026-05-01",
                "low_since": "2026-08-20",
                "meter_readings": readings,
            }
        },
    )

    update_battery_history({SERIAL: "NORMAL"})
    update_battery_history({SERIAL: "LOW"})

    assert load_battery_history()[SERIAL]["meter_readings"] == readings


def test_replacing_a_battery_keeps_its_meter_readings(frozen_today, history_file):
    readings = [{"date": "2026-08-20", "percent": [30, 40]}]
    _write(
        history_file,
        {
            SERIAL: {
                "good_since": "2026-05-01",
                "low_since": "2026-08-20",
                "meter_readings": readings,
            }
        },
    )

    mark_battery_replaced(SERIAL)

    entry = load_battery_history()[SERIAL]
    assert entry["past_batteries"][0]["meter_readings"] == readings
    assert "meter_readings" not in entry


# --- readings for the batteries already taken out ---------------------------

OLD_SET = {
    "fitted": "2026-05-01",
    "went_low": None,
    "replaced": "2026-08-20",
    "days": 111,
    "minimum": True,
}


def test_a_meter_reading_can_go_on_the_set_last_taken_out(frozen_today, history_file):
    earlier = {**OLD_SET, "fitted": "2026-01-01", "replaced": "2026-05-01"}
    _write(
        history_file,
        {
            SERIAL: {
                "good_since": "2026-08-20",
                "low_since": None,
                "past_batteries": [earlier, OLD_SET],
            }
        },
    )

    reading, replaced = add_meter_reading(SERIAL, [50, 50], note="changed early", old_set=True)

    assert replaced == "2026-08-20"

    # Dated the day they came out unless told otherwise
    assert reading == {"date": "2026-08-20", "percent": [50, 50], "note": "changed early"}
    entry = load_battery_history()[SERIAL]
    assert entry["past_batteries"][-1]["meter_readings"] == [reading]
    assert "meter_readings" not in entry["past_batteries"][0]
    assert "meter_readings" not in entry


def test_an_old_set_reading_can_be_backdated(frozen_today, history_file):
    _write(
        history_file,
        {SERIAL: {"good_since": "2026-08-20", "low_since": None, "past_batteries": [OLD_SET]}},
    )

    reading, _ = add_meter_reading(SERIAL, [40], on="2026-08-19", old_set=True)

    assert reading["date"] == "2026-08-19"


def test_an_old_set_reading_is_refused_with_nothing_taken_out(frozen_today, history_file):
    _write(history_file, {SERIAL: {"good_since": "2026-05-01", "low_since": None}})

    with pytest.raises(NoOldBatteries):
        add_meter_reading(SERIAL, [50], old_set=True)
    assert "meter_readings" not in history_file.read_text()
