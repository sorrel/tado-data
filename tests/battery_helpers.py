"""
Fakes and seeding shared by the battery tests. Nothing here reaches Tado.
"""

import json

import tado_data.commands.battery
import tado_data.commands.battery_history
import tado_data.commands.device_lookup


def fake_tado(monkeypatch, client_class):
    """Use CLIENT_CLASS in place of TadoClient in every battery command."""
    for module in (
        tado_data.commands.battery,
        tado_data.commands.battery_history,
        tado_data.commands.device_lookup,
    ):
        monkeypatch.setattr(module, "TadoClient", client_class)


class FakeClient:
    """Stands in for TadoClient; returns whatever zones it was handed."""

    def __init__(self, zones):
        self._zones = zones

    def get_zones(self):
        return self._zones


class FakeReportClient:
    """Stands in for TadoClient for a whole report; no network."""

    def connect(self):
        return True

    def get_devices(self):
        return [
            {
                "serialNo": "VA1",
                "shortSerialNo": "VA1",
                "deviceType": "VA01",
                "batteryState": "NORMAL",
            }
        ]

    def get_zones(self):
        return [{"name": "Lounge", "devices": [{"serialNo": "VA1"}]}]


def _past(fitted, days, minimum=False):
    return {
        "fitted": fitted,
        "went_low": "2026-11-09",
        "replaced": "2026-11-10",
        "days": days,
        "minimum": minimum,
    }


def _seed_history(history_file, past_batteries):
    history_file.write_text(
        json.dumps(
            {
                "devices": {
                    "VA1": {
                        "good_since": "2026-11-10",
                        "low_since": None,
                        "past_batteries": past_batteries,
                    },
                }
            }
        )
    )


def _seed(history_file, entry):
    history_file.write_text(json.dumps({"devices": {"VA1": entry}}))
    return lambda: json.loads(history_file.read_text())["devices"]["VA1"]


class FakeRoomClient:
    """Stands in for TadoClient when a room name is looked up; no network."""

    def connect(self):
        return True

    def get_zones(self):
        return [
            {"name": "Hall", "devices": [{"serialNo": "VA1"}, {"serialNo": "SU3893321984"}]},
            {"name": "Kitchen", "devices": [{"serialNo": "VA2"}]},
            {"name": "Main Bedroom", "devices": [{"serialNo": "VA3"}, {"serialNo": "VA4"}]},
        ]


ROOM_HISTORY = {
    "devices": {
        serial: {"good_since": "2026-05-01", "low_since": "2026-08-20"}
        for serial in ["VA1", "VA2", "VA3", "VA4", "SU3893321984"]
    }
}
