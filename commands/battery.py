"""
The battery report: every battery device's state, age and low warnings.
"""

from datetime import date

import click

from commands.battery_format import (
    AGE_BANDS,
    MAKE_STYLE,
    NO_VALUE,
    age_colour,
    format_average,
    format_last,
)
from commands.device_lookup import device_zone_map
from commands.table import cell, count, echo_header
from core.battery_devices import BatteryDevice, battery_devices, record_battery_states
from core.client import TadoClient
from core.storage import NEW_DEVICE, BatteryHistory, DeviceHistory, LowPeriod


@click.command("battery")
@click.option(
    "-r", "--room", default=None, help="Filter by room/zone name (case-insensitive substring)."
)
def battery_command(room):
    """Show battery status for all battery-powered devices."""
    client = TadoClient()
    if not client.connect():
        return

    devices = client.get_devices()
    if not devices:
        click.echo("No devices found.")
        return

    found = battery_devices(devices, device_zone_map(client), room)
    if not found:
        click.echo("No battery-powered devices found.")
        return

    history = record_battery_states(found)
    found.sort(key=lambda d: (d.zone, d.type, d.name))
    _print_battery_table(found, history)
    _print_battery_summary(found)


def _print_battery_table(devices: list[BatteryDevice], history: BatteryHistory) -> None:
    """Print one row per device, under a header sized to fit."""
    zone_width = max(len(d.zone) for d in devices)
    type_width = max(len(d.type) for d in devices)
    name_width = max(len(d.name) for d in devices)

    header = (
        f"  {'Zone':<{zone_width}}  "
        f"{'Type':<{type_width}}  "
        f"{'Serial':<{name_width}}  "
        f"{'Battery':>8}  "
        f"{'Good since':<10}  "
        f"{'Age':>6}  "
        f"{'Last':>6}  "
        f"{'Average':>8}  "
        f"{'First low':<10}  "
        f"{'Latest low':<10}  "
        f"{'Lows':>4}  "
        f"{'Connected':>9}  "
        "Make"
    )
    click.echo()
    echo_header(header)

    for d in devices:
        device = f"  {d.zone:<{zone_width}}  {d.type:<{type_width}}  {d.name:<{name_width}}"
        entry = history.get(d.serial, NEW_DEVICE)
        cells = _mains_cells() if d.mains else _battery_cells(d, entry)
        make = "" if d.mains else cell(entry.get("make", ""), 0, **MAKE_STYLE)
        row = "  ".join([device, *cells, _format_connected(d.connected), make])
        click.echo(row.rstrip())


def _mains_cells() -> list[str]:
    """The battery columns for a mains-wired device, which has no meaningful battery data."""
    na = "N/A"
    return [
        click.style(f"{na:>8}", fg="bright_black"),
        click.style(f"{na:<10}", fg="bright_black"),
        click.style(f"{na:>6}", fg="bright_black"),
        click.style(f"{na:>6}", fg="bright_black"),
        click.style(f"{na:>8}", fg="bright_black"),
        click.style(f"{na:<10}  {na:<10}  {na:>4}", fg="bright_black"),
    ]


def _battery_cells(device: BatteryDevice, entry: DeviceHistory) -> list[str]:
    """The battery columns: state, good since, age, lifespans and low warnings."""
    if device.is_low:
        battery_str = click.style(f"{'LOW':>8}", fg="red", bold=True)
    else:
        battery_str = click.style(f"{'Normal':>8}", fg="green")

    # Days since the battery went in, coloured in 100-day bands
    good_since = entry.get("good_since")
    days = _days_since(good_since)
    if days is None:
        age_str = f"{NO_VALUE:>6}"
    else:
        age_str = click.style(f"{days:>5}d", fg=age_colour(days), bold=True)

    return [
        battery_str,
        f"{good_since or '':<10}",
        age_str,
        format_last(past := entry.get("past_batteries", [])),
        format_average(past),
        _format_lows(entry.get("low_periods", []), device.is_low),
    ]


def _format_connected(connected: bool) -> str:
    return (
        click.style(f"{'Yes':>9}", fg="green") if connected else click.style(f"{'No':>9}", fg="red")
    )


def _print_battery_summary(devices: list[BatteryDevice]) -> None:
    """Print the device count, how many are low, and the key to the age colours."""
    mains_count = sum(1 for d in devices if d.mains)
    low_count = sum(1 for d in devices if not d.mains and d.is_low)
    total = len(devices) - mains_count

    click.echo()
    summary = f"  {count(total, 'battery-powered device')}"
    if mains_count:
        summary += click.style(f" (+{mains_count} mains-wired)", fg="bright_black")
    if low_count:
        summary += click.style(f" ({low_count} LOW)", fg="red", bold=True)
    else:
        summary += click.style(" (all normal)", fg="green")
    click.echo(summary)

    labels = ["<100d", "100-199d", "200-299d", "300-399d", "400d+"]
    legend = "  ".join(
        click.style(label, fg=colour, bold=True)
        for label, colour in zip(labels, AGE_BANDS, strict=True)
    )
    click.echo(click.style("  Age: ", fg="bright_black") + legend)
    click.echo()


def _format_lows(periods: list[LowPeriod], is_low: bool) -> str:
    """Format the first day seen low, the most recent and how many spells; red only while low."""
    if not periods:
        return " " * 28
    latest = periods[-1].get("seen") or periods[-1]["from"]
    text = f"{periods[0]['from']:<10}  {latest:<10}  {len(periods):>4}"
    return click.style(text, fg="red") if is_low else text


def _days_since(iso_date: str | None) -> int | None:
    """Return whole days between an ISO date string and today, or None if unparseable."""
    if not iso_date:
        return None
    try:
        return (date.today() - date.fromisoformat(iso_date)).days
    except ValueError:
        return None
