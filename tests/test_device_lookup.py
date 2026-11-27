"""
Choosing a device by serial or rough room name, and tab completion.

No test reaches Tado: a fake client stands in, per CLAUDE.md.
"""

import json

import pytest
from click.testing import CliRunner

from tado_data.commands.battery_record import (
    battery_reading_command,
    battery_replaced_command,
)
from tado_data.commands.device_lookup import complete_device, device_zone_map, match_rooms
from tests.battery_helpers import (
    ROOM_HISTORY,
    FakeClient,
    FakeRoomClient,
    fake_tado,
)


def test_maps_serial_numbers_to_zone_names():
    client = FakeClient(
        [
            {"name": "Lounge", "devices": [{"serialNo": "AAA"}, {"serialNo": "BBB"}]},
            {"name": "Kitchen", "devices": [{"serialNo": "CCC"}]},
        ]
    )

    assert device_zone_map(client) == {
        "AAA": "Lounge",
        "BBB": "Lounge",
        "CCC": "Kitchen",
    }


def test_zone_without_a_name_falls_back_to_unknown():
    client = FakeClient([{"devices": [{"serialNo": "AAA"}]}])

    assert device_zone_map(client) == {"AAA": "Unknown"}


def test_devices_without_a_serial_are_skipped():
    client = FakeClient(
        [
            {"name": "Lounge", "devices": [{"serialNo": "AAA"}, {"shortSerialNo": "no-serial"}]},
        ]
    )

    assert device_zone_map(client) == {"AAA": "Lounge"}


def test_zone_with_no_devices_contributes_nothing():
    client = FakeClient([{"name": "Empty room"}])

    assert device_zone_map(client) == {}


@pytest.mark.parametrize("zones", [None, []])
def test_returns_empty_map_when_zones_unavailable(zones):
    """get_zones() returns None when the API call fails."""
    assert device_zone_map(FakeClient(zones)) == {}


ROOMS = ["Bathroom", "Downstairs Loo", "Hall", "Kitchen", "Main Bedroom", "Spare Bedroom"]


@pytest.mark.parametrize(
    "query,expected,close",
    [
        ("hall", ["Hall"], False),
        ("downstairs-loo", ["Downstairs Loo"], False),
        ("loo", ["Downstairs Loo"], False),
        ("bedroom", ["Main Bedroom", "Spare Bedroom"], False),
        ("kitchn", ["Kitchen"], True),
        ("bathrm", ["Bathroom"], True),
        ("dwnstairs loo", ["Downstairs Loo"], True),
        ("garage", [], True),
        ("", [], False),
    ],
)
def test_match_rooms(query, expected, close):
    assert match_rooms(query, ROOMS) == (expected, close)


@pytest.fixture
def rooms(frozen_today, history_file, monkeypatch):
    history_file.write_text(json.dumps(ROOM_HISTORY))
    fake_tado(monkeypatch, FakeRoomClient)
    return history_file


def test_replaced_command_takes_a_room_name(rooms):
    result = CliRunner().invoke(battery_replaced_command, ["hall"], input="\n\n")

    assert result.exit_code == 0, result.output
    assert "Hall: VA1" in result.output  # the mains-wired thermostat is left out
    assert json.loads(rooms.read_text())["devices"]["VA1"]["past_batteries"][0]["days"] == 111


def test_a_misspelt_room_is_confirmed_first(rooms):
    declined = CliRunner().invoke(battery_replaced_command, ["kitchn"], input="n\n")
    assert declined.exit_code != 0
    assert "past_batteries" not in rooms.read_text()

    accepted = CliRunner().invoke(battery_replaced_command, ["kitchn"], input="y\n\n\n")
    assert accepted.exit_code == 0, accepted.output
    assert "Kitchen (VA2)" in accepted.output
    assert "past_batteries" in json.loads(rooms.read_text())["devices"]["VA2"]


def test_a_room_with_two_devices_asks_for_the_serial(rooms):
    result = CliRunner().invoke(battery_replaced_command, ["main bedroom"])

    assert result.exit_code != 0
    assert "VA3" in result.output and "VA4" in result.output
    assert "past_batteries" not in rooms.read_text()


def test_an_unknown_room_lists_the_rooms(rooms):
    result = CliRunner().invoke(battery_replaced_command, ["garage"])

    assert result.exit_code != 0
    assert "Hall, Kitchen, Main Bedroom" in result.output


def test_reading_command_takes_a_room_name(rooms):
    result = CliRunner().invoke(battery_reading_command, ["kitchen", "30", "40"])

    assert result.exit_code == 0, result.output
    assert json.loads(rooms.read_text())["devices"]["VA2"]["meter_readings"][0]["percent"] == [
        30,
        40,
    ]


def test_a_serial_never_contacts_tado(frozen_today, history_file, monkeypatch):
    history_file.write_text(json.dumps(ROOM_HISTORY))

    class NoClient:
        def __init__(self):
            raise AssertionError("a serial must not need Tado")

    fake_tado(monkeypatch, NoClient)
    result = CliRunner().invoke(battery_replaced_command, ["va1"], input="\n\n")

    assert result.exit_code == 0, result.output


def test_fetching_zones_saves_room_names(room_names_file):
    device_zone_map(FakeClient([{"name": "Lounge", "devices": [{"serialNo": "AAA"}]}]))

    assert json.loads(room_names_file.read_text()) == {"AAA": "Lounge"}


def _offered(incomplete):
    return [(item.value, item.help) for item in complete_device(None, None, incomplete)]


def test_completion_offers_rooms_then_serials(frozen_today, history_file, room_names_file):
    history_file.write_text(json.dumps(ROOM_HISTORY))
    room_names_file.write_text(
        json.dumps(
            {
                "VA1": "Hall",
                "SU3893321984": "Hall",
                "VA2": "Kitchen",
                "VA3": "Main Bedroom",
                "VA4": "Main Bedroom",
            }
        )
    )

    assert _offered("") == [
        ("Hall", "VA1"),
        ("Kitchen", "VA2"),
        ("Main Bedroom", "VA3, VA4"),
        ("VA1", "Hall"),
        ("VA2", "Kitchen"),
        ("VA3", "Main Bedroom"),
        ("VA4", "Main Bedroom"),
    ]
    assert _offered("bed") == [("Main Bedroom", "VA3, VA4")]
    assert _offered("va2") == [("VA2", "Kitchen")]


def test_completion_never_contacts_tado_and_copes_without_room_names(
    frozen_today, history_file, monkeypatch
):
    history_file.write_text(json.dumps(ROOM_HISTORY))
    fake_tado(monkeypatch, None)

    assert _offered("") == [("VA1", ""), ("VA2", ""), ("VA3", ""), ("VA4", "")]


def test_completion_offers_nothing_for_a_damaged_history(history_file):
    history_file.write_text("{ not json")

    assert _offered("") == []
