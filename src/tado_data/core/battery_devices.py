"""
The devices that run on batteries, as Tado lists them, and saving what they report.

Shared by the battery report and the scheduled battery check, so both read
Tado's device list the same way and save to the history the same way.
"""

from dataclasses import dataclass

from tado_data.core.storage import BatteryHistory, save_room_names, update_battery_history

# Devices that are mains-wired despite reporting a batteryState. The hall thermostat
# is wired in, so its battery columns are meaningless — reported as N/A.
MAINS_WIRED_SERIALS = {"SU3893321984"}


@dataclass(frozen=True)
class BatteryDevice:
    """One device that reports a battery state, with the room it is in."""

    serial: str
    name: str  # the short serial Tado shows
    type: str  # VA01, RU02, …
    zone: str
    battery: str  # "NORMAL" or "LOW"
    connected: bool

    @property
    def mains(self) -> bool:
        """Wired in, so its battery state means nothing."""
        return self.serial in MAINS_WIRED_SERIALS

    @property
    def is_low(self) -> bool:
        return self.battery == "LOW"


def device_rooms(zones: list[dict]) -> dict[str, str]:
    """Map each device's serial to its zone's name, and remember the map."""
    device_zones = {}
    for zone in zones:
        zone_name = zone.get("name", "Unknown")
        for device in zone.get("devices", []):
            serial = device.get("serialNo")
            if serial:
                device_zones[serial] = zone_name
    save_room_names(device_zones)
    return device_zones


def battery_devices(
    devices: list[dict], device_zones: dict[str, str], room: str | None = None
) -> list[BatteryDevice]:
    """The devices that report a battery state, in ROOM (any part of its name) if given."""
    found = []
    for device in devices:
        battery_state = device.get("batteryState")
        if battery_state is None:
            continue
        serial = device.get("serialNo", "")
        zone_name = device_zones.get(serial, "Unassigned")
        if room and room.lower() not in zone_name.lower():
            continue
        found.append(
            BatteryDevice(
                serial=serial,
                name=device.get("shortSerialNo", serial),
                type=device.get("deviceType", "Unknown"),
                zone=zone_name,
                battery=battery_state,
                connected=device.get("connectionState", {}).get("value", False),
            )
        )
    return found


def record_battery_states(devices: list[BatteryDevice]) -> BatteryHistory:
    """Save what each battery device reports today to the history, and return the history."""
    on_battery = [d for d in devices if not d.mains]
    current_states = {d.serial: d.battery for d in on_battery}
    disconnected = {d.serial for d in on_battery if not d.connected}
    return update_battery_history(current_states, disconnected)
