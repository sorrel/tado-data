"""
Zones command — shows which devices are zone controllers vs TRVs.
"""

import click

from tado_data.commands.table import count, echo_header
from tado_data.core.client import TadoClient


@click.command("zones")
def zones_command():
    """Show which devices directly fire the boiler (zone controllers) vs TRVs."""
    client = TadoClient()
    if not client.connect():
        return

    zones = client.get_zones()
    if not zones:
        click.echo("No zones found.")
        return

    rows = []
    for zone in zones:
        if zone.get("type") != "HEATING":
            continue
        zone_id = zone["id"]
        zone_name = zone.get("name", "Unknown")
        control = client.get_zone_control(zone_id)
        fires_boiler = bool(control and control.get("heatingCircuit") is not None)
        for device in zone.get("devices", []):
            serial = device.get("shortSerialNo", device.get("serialNo", ""))
            device_type = device.get("deviceType", "Unknown")
            rows.append(
                {
                    "zone": zone_name,
                    "serial": serial,
                    "type": device_type,
                    "fires_boiler": fires_boiler,
                }
            )

    if not rows:
        click.echo("No devices found in zones.")
        return

    # Zone controllers first, then alphabetically by zone name
    rows.sort(key=lambda r: (not r["fires_boiler"], r["zone"], r["type"]))

    zone_width = max(len(r["zone"]) for r in rows)
    serial_width = max(len(r["serial"]) for r in rows)
    type_width = max(len(r["type"]) for r in rows)

    header = (
        f"  {'Zone':<{zone_width}}  "
        f"{'Serial':<{serial_width}}  "
        f"{'Type':<{type_width}}  "
        f"{'Fires Boiler':>12}"
    )
    click.echo()
    echo_header(header)

    for r in rows:
        if r["fires_boiler"]:
            fires_str = click.style(f"{'✓':>12}", fg="green", bold=True)
        else:
            fires_str = f"{'':>12}"

        click.echo(
            f"  {r['zone']:<{zone_width}}  "
            f"{r['serial']:<{serial_width}}  "
            f"{r['type']:<{type_width}}  "
            f"{fires_str}"
        )

    controller_count = sum(1 for r in rows if r["fires_boiler"])
    total = len(rows)
    click.echo()
    fire = "fires" if controller_count == 1 else "fire"
    click.echo(f"  {count(total, 'device')}, {controller_count} {fire} boiler")
    click.echo()
