"""
Battery reporting command.
"""

import click
from datetime import date

from core.client import TadoClient
from core.storage import update_battery_history


def _get_device_zone_map(client: TadoClient) -> dict:
    """
    Build a mapping of device serial number to zone name and controller status.

    Returns dict of {serial_no: {"zone": zone_name, "is_controller": bool}}.
    A device with ZONE_LEADER duty is the zone controller that fires the boiler.
    """
    zones = client.get_zones()
    if not zones:
        return {}

    device_zones = {}
    for zone in zones:
        zone_name = zone.get("name", "Unknown")
        for device in zone.get("devices", []):
            serial = device.get("serialNo")
            if serial:
                duties = device.get("duties", [])
                device_zones[serial] = {
                    "zone": zone_name,
                    "is_controller": "ZONE_LEADER" in duties,
                }
    return device_zones


@click.command("battery")
@click.option("-r", "--room", default=None, help="Filter by room/zone name (case-insensitive substring).")
def battery_command(room):
    """Show battery status for all battery-powered devices."""
    client = TadoClient()
    if not client.connect():
        return

    devices = client.get_devices()
    if not devices:
        click.echo("No devices found.")
        return

    # Build zone mapping
    device_zones = _get_device_zone_map(client)

    # Filter to battery-powered devices
    battery_devices = []
    for device in devices:
        battery_state = device.get("batteryState")
        if battery_state is None:
            continue

        serial = device.get("serialNo", "")
        zone_info = device_zones.get(serial, {"zone": "Unassigned", "is_controller": False})
        zone_name = zone_info["zone"]

        # Apply room filter
        if room and room.lower() not in zone_name.lower():
            continue

        battery_devices.append({
            "serial": serial,
            "name": device.get("shortSerialNo", serial),
            "type": device.get("deviceType", "Unknown"),
            "zone": zone_name,
            "battery": battery_state,
            "connection": device.get("connectionState", {}).get("value", False),
            "firmware": device.get("currentFwVersion", ""),
            "is_controller": zone_info["is_controller"],
        })

    if not battery_devices:
        click.echo("No battery-powered devices found.")
        return

    # Update persistent history and get date fields
    current_states = {d["serial"]: d["battery"] for d in battery_devices}
    history = update_battery_history(current_states)
    today = date.today().isoformat()

    for d in battery_devices:
        entry = history.get(d["serial"], {})
        d["good_since"] = entry.get("good_since")
        d["low_since"] = entry.get("low_since")

    # Sort by zone, then device type
    battery_devices.sort(key=lambda d: (d["zone"], d["type"], d["name"]))

    # Calculate column widths
    zone_width = max(len(d["zone"]) for d in battery_devices)
    type_width = max(len(d["type"]) for d in battery_devices)
    name_width = max(len(d["name"]) for d in battery_devices)

    # Header
    header = (
        f"  {'Zone':<{zone_width}}  "
        f"{'Type':<{type_width}}  "
        f"{'Serial':<{name_width}}  "
        f"{'Battery':>8}  "
        f"{'Good since':<10}  "
        f"{'Low since':<10}  "
        f"{'Boiler':>6}  "
        f"{'Connected':>9}"
    )
    click.echo()
    click.echo(click.style(header, fg="bright_white", bold=True))
    click.echo(click.style("  " + "─" * (len(header) - 2), fg="bright_black"))

    # Rows
    low_count = 0
    for d in battery_devices:
        # Colour the battery status
        if d["battery"] == "LOW":
            battery_str = click.style(f"{'LOW':>8}", fg="red", bold=True)
            low_count += 1
        else:
            battery_str = click.style(f"{'Normal':>8}", fg="green")

        # Good since — dim if first seen today
        good_since = d["good_since"] or ""
        if good_since == today:
            good_str = click.style(f"{good_since:<10}", fg="bright_black")
        else:
            good_str = f"{good_since:<10}"

        # Low since — red if set, blank otherwise
        low_since = d["low_since"] or ""
        if low_since:
            low_str = click.style(f"{low_since:<10}", fg="red")
        else:
            low_str = f"{'':<10}"

        # Zone controller (fires boiler)
        if d["is_controller"]:
            boiler_str = click.style(f"{'Yes':>6}", fg="green")
        else:
            boiler_str = click.style(f"{'No':>6}", fg="bright_black")

        # Colour connection status
        connected = d["connection"]
        if connected:
            conn_str = click.style(f"{'Yes':>9}", fg="green")
        else:
            conn_str = click.style(f"{'No':>9}", fg="red")

        click.echo(
            f"  {d['zone']:<{zone_width}}  "
            f"{d['type']:<{type_width}}  "
            f"{d['name']:<{name_width}}  "
            f"{battery_str}  "
            f"{good_str}  "
            f"{low_str}  "
            f"{boiler_str}  "
            f"{conn_str}"
        )

    # Summary
    total = len(battery_devices)
    click.echo()
    summary = f"  {total} battery-powered device{'s' if total != 1 else ''}"
    if low_count:
        summary += click.style(f" ({low_count} LOW)", fg="red", bold=True)
    else:
        summary += click.style(" (all normal)", fg="green")
    click.echo(summary)
    click.echo()
