"""
Decide which battery changes to notify, for the scheduled daily check.

Only a change is worth a notification: a device going LOW, going back to
NORMAL, going offline while LOW (taken to have died) or coming back. The
history moving on by a day, with `seen` advancing on a spell already known,
is not. Pure: it compares the history before and after one update.
"""

from core.storage import NEW_DEVICE, BatteryHistory, DeviceHistory


def _is_low(entry: DeviceHistory) -> bool:
    periods = entry.get("low_periods")
    if periods:
        return periods[-1]["to"] is None
    # A low date saved before low spells were recorded counts as an open spell
    return bool(entry.get("low_since"))


def battery_changes(
    before: BatteryHistory, after: BatteryHistory, labels: dict[str, str]
) -> list[str]:
    """
    The lines to notify, one per change, in the order of `after`.

    labels: {serial: what to call the device}, falling back to the serial.
    """
    lines = []
    for serial, entry in after.items():
        old = before.get(serial, NEW_DEVICE)
        name = labels.get(serial, serial)
        was_low, is_low = _is_low(old), _is_low(entry)
        if is_low and not was_low:
            lines.append(f"{name} batteries are low")
        elif was_low and not is_low:
            lines.append(f"{name} batteries are back to normal")
        if entry.get("died") and not old.get("died"):
            lines.append(f"{name} has gone offline with low batteries")
        elif old.get("died") and not entry.get("died"):
            lines.append(f"{name} is back online")
    return lines
