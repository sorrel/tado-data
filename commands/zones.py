"""
Zones command — shows which devices are zone controllers vs TRVs.
"""

import click

from core.client import TadoClient


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
        zone_name = zone.get("name", "Unknown")
        for device in zone.get("devices", []):
            serial = device.get("shortSerialNo", device.get("serialNo", ""))
            device_type = device.get("deviceType", "Unknown")
            duties = device.get("duties", [])
            rows.append({
                "zone": zone_name,
                "serial": serial,
                "type": device_type,
                "fires_boiler": "IS_ZONE_LEADER" in duties,
            })

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
    click.echo(click.style(header, fg="bright_white", bold=True))
    click.echo(click.style("  " + "─" * (len(header) - 2), fg="bright_black"))

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
    click.echo(
        f"  {total} device{'s' if total != 1 else ''}, "
        f"{controller_count} zone controller{'s' if controller_count != 1 else ''}"
    )
    click.echo()
