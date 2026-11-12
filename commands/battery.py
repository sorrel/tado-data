"""
Battery reporting command.
"""

import difflib
import re
from datetime import date

import click
from click.shell_completion import CompletionItem

from core.client import TadoClient
from core.storage import (
    add_meter_reading,
    load_battery_history,
    load_room_names,
    mark_battery_replaced,
    save_room_names,
    update_battery_history,
)

# Colour bands for battery age, one per 100 days. Bright colours for a black background.
AGE_BANDS = ["bright_green", "bright_cyan", "bright_yellow", "bright_magenta", "bright_red"]

# Devices that are mains-wired despite reporting a batteryState. The hall thermostat
# is wired in, so its battery columns are meaningless — reported as N/A.
MAINS_WIRED_SERIALS = {"SU3893321984"}


def _days_since(iso_date: str | None) -> int | None:
    """Return whole days between an ISO date string and today, or None if unparseable."""
    if not iso_date:
        return None
    try:
        return (date.today() - date.fromisoformat(iso_date)).days
    except ValueError:
        return None


def _age_colour(days: int) -> str:
    """Pick a colour for a battery age, changing every 100 days."""
    band = min(days // 100, len(AGE_BANDS) - 1)
    return AGE_BANDS[band]


def _format_last(past_batteries: list[dict]) -> str:
    """Format how long the previous battery lasted, marking unknown-age ones as a minimum."""
    if not past_batteries:
        return f"{'':>6}"
    last = past_batteries[-1]
    label = f"≥{last['days']}d" if last.get("minimum") else f"{last['days']}d"
    return click.style(f"{label:>6}", fg=_age_colour(last["days"]), bold=True)


def _format_lows(periods: list[dict], is_low: bool) -> str:
    """Format the first low warning, the latest and how many; red only while still low."""
    if not periods:
        return " " * 28
    text = f"{periods[0]['from']:<10}  {periods[-1]['from']:<10}  {len(periods):>4}"
    return click.style(text, fg="red") if is_low else text


def _average_days(lifespans: list[dict]) -> int | None:
    """Average the measured lifespans, leaving out unknown-age minimums."""
    measured = [b["days"] for b in lifespans if not b.get("minimum")]
    if not measured:
        return None
    return round(sum(measured) / len(measured))


def _on_low(battery: dict) -> dict | None:
    """How long a battery kept going once low; a minimum if it was replaced before dying."""
    if not battery.get("went_low"):
        return None  # taken out before it ever warned
    died = battery.get("died")
    end = date.fromisoformat(died or battery["replaced"])
    return {"days": (end - date.fromisoformat(battery["went_low"])).days, "minimum": not died}


def _get_device_zone_map(client: TadoClient) -> dict:
    """Build a mapping of device serial number to zone name."""
    zones = client.get_zones()
    if not zones:
        return {}

    device_zones = {}
    for zone in zones:
        zone_name = zone.get("name", "Unknown")
        for device in zone.get("devices", []):
            serial = device.get("serialNo")
            if serial:
                device_zones[serial] = zone_name
    save_room_names(device_zones)
    return device_zones


# A Tado serial: two letters then digits, such as VA0149052928. Anything else is a room name.
SERIAL_PATTERN = re.compile(r"^[A-Za-z]{2}\d+$")


def _squash(text: str) -> str:
    """Lower-case and drop spaces and punctuation, so "downstairs-loo" finds "Downstairs Loo"."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _match_rooms(query: str, rooms: list[str]) -> tuple[list[str], bool]:
    """
    Find the rooms a rough name could mean.

    Tries an exact match, then rooms containing the query, then close spellings.
    Returns the rooms found and whether the match was only a close spelling,
    which is worth confirming.
    """
    wanted = _squash(query)
    if not wanted:
        return [], False
    squashed = {room: _squash(room) for room in rooms}

    exact = [room for room, name in squashed.items() if name == wanted]
    if exact:
        return exact, False
    containing = [room for room, name in squashed.items() if wanted in name]
    if containing:
        return containing, False

    # Close spellings, of the whole name or of any one word in it ("bathrm", "kitchn").
    def score(room: str) -> float:
        candidates = [squashed[room], *(_squash(word) for word in room.split())]
        return max(difflib.SequenceMatcher(None, wanted, c).ratio() for c in candidates)

    scores = {room: score(room) for room in rooms}
    best = max(scores.values(), default=0)
    if best < 0.75:
        return [], True
    return [room for room, s in scores.items() if s == best], True


def _complete_device(ctx, param, incomplete: str) -> list[CompletionItem]:
    """
    Offer room names and serials for tab completion, from local files only.

    Pressing Tab must never contact Tado, so rooms come from the names saved
    the last time a battery command fetched them.
    """
    try:
        history = load_battery_history()
    except click.ClickException:
        return []
    serials = sorted(s for s in history if s not in MAINS_WIRED_SERIALS)
    room_names = load_room_names()
    wanted = _squash(incomplete)

    rooms: dict[str, list[str]] = {}
    for serial in serials:
        if serial in room_names:
            rooms.setdefault(room_names[serial], []).append(serial)

    items = [
        CompletionItem(room, help=", ".join(found))
        for room, found in sorted(rooms.items())
        if wanted in _squash(room)
    ]
    items += [
        CompletionItem(serial, help=room_names.get(serial, ""))
        for serial in serials
        if serial.lower().startswith(incomplete.lower())
    ]
    return items


def _resolve_device(name: str, action: str) -> str:
    """
    Turn a serial or a rough room name into the serial of a device with battery history.

    A serial is used as it is, with no request to Tado. A room name needs the
    zone list from Tado to find which devices are in it.
    """
    if SERIAL_PATTERN.match(name):
        return name.upper()

    history = load_battery_history()
    client = TadoClient()
    if not client.connect():
        raise click.ClickException("Couldn't reach Tado to look up room names. Use the device's serial instead.")
    device_zones = _get_device_zone_map(client)

    rooms: dict[str, list[str]] = {}
    for serial, zone in device_zones.items():
        if serial in history and serial not in MAINS_WIRED_SERIALS:
            rooms.setdefault(zone, []).append(serial)

    found, close_only = _match_rooms(name, sorted(rooms))
    if not found:
        raise click.ClickException(
            f"No room matches \"{name}\". Rooms with battery devices: {', '.join(sorted(rooms))}."
        )
    if len(found) > 1:
        raise click.ClickException(f"\"{name}\" could be {', '.join(found)}. Be more specific.")

    room = found[0]
    serials = sorted(rooms[room])
    if len(serials) > 1:
        def label(serial: str) -> str:
            periods = history[serial].get("low_periods", [])
            return f"{serial} (low)" if periods and periods[-1].get("to") is None else serial
        raise click.ClickException(
            f"{room} has {len(serials)} battery devices: {', '.join(label(s) for s in serials)}. Give the serial instead."
        )

    serial = serials[0]
    if close_only:
        click.confirm(f"{action} {room} ({serial})?", default=True, abort=True)
    else:
        click.echo(f"{room}: {serial}")
    return serial


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
        zone_name = device_zones.get(serial, "Unassigned")

        # Apply room filter
        if room and room.lower() not in zone_name.lower():
            continue

        battery_devices.append({
            "serial": serial,
            "mains": serial in MAINS_WIRED_SERIALS,
            "name": device.get("shortSerialNo", serial),
            "type": device.get("deviceType", "Unknown"),
            "zone": zone_name,
            "battery": battery_state,
            "connection": device.get("connectionState", {}).get("value", False),
            "firmware": device.get("currentFwVersion", ""),
        })

    if not battery_devices:
        click.echo("No battery-powered devices found.")
        return

    # Update persistent history and get date fields
    current_states = {d["serial"]: d["battery"] for d in battery_devices if not d["mains"]}
    disconnected = {d["serial"] for d in battery_devices if not d["mains"] and not d["connection"]}
    history = update_battery_history(current_states, disconnected)

    for d in battery_devices:
        entry = history.get(d["serial"], {})
        d["good_since"] = entry.get("good_since")
        d["low_periods"] = entry.get("low_periods", [])
        d["past_batteries"] = entry.get("past_batteries", [])

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
        f"{'Age':>6}  "
        f"{'Last':>6}  "
        f"{'First low':<10}  "
        f"{'Latest low':<10}  "
        f"{'Lows':>4}  "
        f"{'Connected':>9}"
    )
    click.echo()
    click.echo(click.style(header, fg="bright_white", bold=True))
    click.echo(click.style("  " + "─" * (len(header) - 2), fg="bright_black"))

    # Rows
    low_count = 0
    for d in battery_devices:
        # Mains-wired devices have no meaningful battery data
        if d["mains"]:
            battery_str = click.style(f"{'N/A':>8}", fg="bright_black")
            good_str = click.style(f"{'N/A':<10}", fg="bright_black")
            age_str = click.style(f"{'N/A':>6}", fg="bright_black")
            last_str = click.style(f"{'N/A':>6}", fg="bright_black")
            low_str = click.style(f"{'N/A':<10}  {'N/A':<10}  {'N/A':>4}", fg="bright_black")
            conn_str = (
                click.style(f"{'Yes':>9}", fg="green")
                if d["connection"]
                else click.style(f"{'No':>9}", fg="red")
            )
            click.echo(
                f"  {d['zone']:<{zone_width}}  "
                f"{d['type']:<{type_width}}  "
                f"{d['name']:<{name_width}}  "
                f"{battery_str}  {good_str}  {age_str}  {last_str}  {low_str}  {conn_str}"
            )
            continue

        # Colour the battery status
        if d["battery"] == "LOW":
            battery_str = click.style(f"{'LOW':>8}", fg="red", bold=True)
            low_count += 1
        else:
            battery_str = click.style(f"{'Normal':>8}", fg="green")

        good_since = d["good_since"] or ""
        good_str = f"{good_since:<10}"

        # Days since the battery went in, coloured in 100-day bands
        days = _days_since(d["good_since"])
        if days is None:
            age_str = f"{'—':>6}"
        else:
            age_str = click.style(f"{days:>5}d", fg=_age_colour(days), bold=True)

        last_str = _format_last(d["past_batteries"])

        low_str = _format_lows(d["low_periods"], d["battery"] == "LOW")

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
            f"{age_str}  "
            f"{last_str}  "
            f"{low_str}  "
            f"{conn_str}"
        )

    # Summary
    mains_count = sum(1 for d in battery_devices if d["mains"])
    total = len(battery_devices) - mains_count
    click.echo()
    summary = f"  {total} battery-powered device{'s' if total != 1 else ''}"
    if mains_count:
        summary += click.style(f" (+{mains_count} mains-wired)", fg="bright_black")
    if low_count:
        summary += click.style(f" ({low_count} LOW)", fg="red", bold=True)
    else:
        summary += click.style(" (all normal)", fg="green")
    click.echo(summary)

    # Age band legend
    labels = ["<100d", "100-199d", "200-299d", "300-399d", "400d+"]
    legend = "  ".join(
        click.style(label, fg=colour, bold=True) for label, colour in zip(labels, AGE_BANDS)
    )
    click.echo(click.style("  Age: ", fg="bright_black") + legend)
    click.echo()


@click.command("battery-replaced")
@click.argument("device", shell_complete=_complete_device)
def battery_replaced_command(device):
    """Record that you have replaced the batteries in DEVICE (a serial, or a room name, roughly)."""
    serial = _resolve_device(device, "Record new batteries in")
    entry = load_battery_history().get(serial, {})
    if entry.get("good_since") == date.today().isoformat() and not entry.get("low_since"):
        click.echo(f"{serial} was already marked as replaced today; nothing changed.")
        return
    try:
        retired = mark_battery_replaced(serial)
    except KeyError:
        raise click.ClickException(f"No battery history for {serial}.")

    if retired and retired["went_low"] is None:
        click.echo(
            f"{serial} marked as replaced. The old set never gave a low warning; it was in for "
            f"{retired['days']} days, saved as a minimum lifespan."
        )
    elif retired:
        prefix = "at least " if retired["minimum"] else ""
        click.echo(f"{serial} marked as replaced. The old set reached its low warning after {prefix}{retired['days']} days.")
    else:
        click.echo(f"{serial} marked as replaced. The old set's dates were unusable, so no lifespan was saved.")


def _format_percents(percents: list[int]) -> str:
    return ", ".join(f"{p}%" for p in percents)


@click.command("battery-reading")
@click.argument("device", shell_complete=_complete_device)
@click.argument("percents", nargs=-1, required=True, type=click.IntRange(0, 100))
@click.option("--date", "on", type=click.DateTime(formats=["%Y-%m-%d"]), help="Day of the reading (YYYY-MM-DD). Defaults to today.")
@click.option("--note", help="Anything worth keeping, such as whether the batteries went back in.")
def battery_reading_command(device, percents, on, note):
    """Record a battery meter's reading, one PERCENT per cell, for DEVICE (a serial, or a room name, roughly)."""
    if on and on.date() > date.today():
        raise click.BadParameter("can't be in the future.", param_hint="--date")
    serial = _resolve_device(device, f"Record {_format_percents(list(percents))} for")
    try:
        reading = add_meter_reading(serial, list(percents), on=on.date().isoformat() if on else None, note=note)
    except KeyError:
        raise click.ClickException(f"No battery history for {serial}.")
    click.echo(f"{serial}: {_format_percents(reading['percent'])} recorded for {reading['date']}.")


def _print_meter_readings(readings: list[tuple[str, dict]], device_zones: dict) -> None:
    """Print every battery meter reading taken, oldest first."""
    rows = sorted(
        ((device_zones.get(serial, "Unassigned"), serial, reading) for serial, reading in readings),
        key=lambda row: (row[2]["date"], row[0]),
    )
    zone_width = max(len("Zone"), *(len(zone) for zone, _, _ in rows))
    serial_width = max(len("Serial"), *(len(serial) for _, serial, _ in rows))
    percents = [_format_percents(reading["percent"]) for _, _, reading in rows]
    percent_width = max(len("Reading"), *(len(p) for p in percents))

    header = f"  {'Zone':<{zone_width}}  {'Serial':<{serial_width}}  {'Date':<10}  {'Reading':<{percent_width}}  Note"
    click.echo(click.style("  Meter readings", fg="bright_white", bold=True))
    click.echo(click.style(header, fg="bright_white", bold=True))
    click.echo(click.style("  " + "─" * (len(header) - 2), fg="bright_black"))
    for (zone, serial, reading), percent in zip(rows, percents):
        click.echo(
            f"  {zone:<{zone_width}}  {serial:<{serial_width}}  {reading['date']:<10}  "
            f"{percent:<{percent_width}}  {reading.get('note', '')}".rstrip()
        )
    click.echo()


def _print_lifespans(lifespans: list[tuple[str, dict]], device_zones: dict) -> None:
    """Print the table of replaced batteries and their averages."""
    rows = sorted(
        ((device_zones.get(serial, "Unassigned"), serial, battery) for serial, battery in lifespans),
        key=lambda row: (row[0], row[2]["fitted"]),
    )
    zone_width = max(len("Zone"), *(len(zone) for zone, _, _ in rows))
    serial_width = max(len("Serial"), *(len(serial) for _, serial, _ in rows))

    header = (
        f"  {'Zone':<{zone_width}}  "
        f"{'Serial':<{serial_width}}  "
        f"{'Fitted':<10}  "
        f"{'Went low':<10}  "
        f"{'Replaced':<10}  "
        f"{'Lasted':>6}  "
        f"{'On low':>6}"
    )
    click.echo()
    click.echo(click.style(header, fg="bright_white", bold=True))
    click.echo(click.style("  " + "─" * (len(header) - 2), fg="bright_black"))

    for zone, serial, battery in rows:
        click.echo(
            f"  {zone:<{zone_width}}  "
            f"{serial:<{serial_width}}  "
            f"{battery['fitted']:<10}  "
            f"{battery['went_low'] or 'never':<10}  "
            f"{battery['replaced']:<10}  "
            f"{_format_last([battery])}  "
            f"{_format_last([on_low]) if (on_low := _on_low(battery)) else f'{chr(8212):>6}'}"
        )

    # Average of the sets whose real lifespan we know
    all_batteries = [battery for _, battery in lifespans]
    measured = sum(1 for battery in all_batteries if not battery.get("minimum"))
    unknown = len(all_batteries) - measured
    average = _average_days(all_batteries)

    click.echo()
    if average is None:
        click.echo("  Average: none yet, every set so far is of unknown age")
    else:
        summary = f"  Average: {average}d from {measured} set{'s' if measured != 1 else ''}"
        if unknown:
            summary += click.style(f" ({unknown} of unknown age not counted)", fg="bright_black")
        click.echo(summary)

    # Only batteries that actually died tell us how long a low one keeps going
    on_low = [low for battery in all_batteries if (low := _on_low(battery))]
    low_average = _average_days(on_low)
    if low_average is not None:
        died = sum(1 for battery in on_low if not battery["minimum"])
        click.echo(f"  Average on low: {low_average}d from {died} set{'s' if died != 1 else ''}")
    click.echo()


def _print_low_periods(lows: list[tuple[str, dict]], device_zones: dict) -> None:
    """Print every spell a device has spent reporting LOW."""
    rows = sorted(
        ((device_zones.get(serial, "Unassigned"), serial, period) for serial, period in lows),
        key=lambda row: (row[0], row[2]["from"]),
    )
    zone_width = max(len("Zone"), *(len(zone) for zone, _, _ in rows))
    serial_width = max(len("Serial"), *(len(serial) for _, serial, _ in rows))

    header = (
        f"  {'Zone':<{zone_width}}  "
        f"{'Serial':<{serial_width}}  "
        f"{'Went low':<10}  "
        f"{'Normal again':<12}  "
        f"{'Days':>6}"
    )
    click.echo(click.style("  Low warnings", fg="bright_white", bold=True))
    click.echo(click.style(header, fg="bright_white", bold=True))
    click.echo(click.style("  " + "─" * (len(header) - 2), fg="bright_black"))

    for zone, serial, period in rows:
        end = date.fromisoformat(period["to"]) if period["to"] else date.today()
        days = (end - date.fromisoformat(period["from"])).days
        click.echo(
            f"  {zone:<{zone_width}}  "
            f"{serial:<{serial_width}}  "
            f"{period['from']:<10}  "
            f"{period['to'] or 'still low':<12}  "
            f"{days:>5}d"
        )
    click.echo()


@click.command("battery-history")
def battery_history_command():
    """Show every replaced battery and low warning, with averages."""
    history = load_battery_history()
    lifespans = [
        (serial, battery)
        for serial, entry in history.items()
        for battery in entry.get("past_batteries", [])
    ]
    lows = [(serial, period) for serial, entry in history.items() for period in entry.get("low_periods", [])]
    lows += [(serial, period) for serial, battery in lifespans for period in battery.get("low_periods", [])]
    readings = [(serial, r) for serial, entry in history.items() for r in entry.get("meter_readings", [])]
    readings += [(serial, r) for serial, battery in lifespans for r in battery.get("meter_readings", [])]

    if not lifespans and not lows and not readings:
        click.echo("No replaced batteries recorded yet.")
        return

    # Room names need the API; the history itself is local, so carry on without them.
    client = TadoClient()
    device_zones = _get_device_zone_map(client) if client.connect() else {}

    if lifespans:
        _print_lifespans(lifespans, device_zones)
    if lows:
        _print_low_periods(lows, device_zones)
    if readings:
        _print_meter_readings(readings, device_zones)
