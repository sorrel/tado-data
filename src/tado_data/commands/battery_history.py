"""
The battery history: every set taken out and how long it lasted, the averages
(overall, by device, by make and by season fitted), low spells and meter readings.
"""

from datetime import date
from pathlib import Path

import click

from tado_data.commands.battery_format import (
    GOOD_STYLE,
    LOW_STYLE,
    MAKE_STYLE,
    NO_VALUE,
    SERIAL_STYLE,
    STILL_LOW_STYLE,
    ZONE_STYLE,
    age_colour,
    average_days,
    format_average,
    format_last,
    format_percents,
)
from tado_data.commands.device_lookup import device_zone_map
from tado_data.commands.table import SECTION_STYLE, cell, count, echo_section
from tado_data.core.battery_seasons import (
    HINT,
    SeasonSummary,
    bar,
    left_out_note,
    longest_average,
    needs_hint,
    season_summaries,
    season_svg,
)
from tado_data.core.client import TadoClient
from tado_data.core.storage import (
    Lifespan,
    LowPeriod,
    MeterReading,
    PastBattery,
    load_battery_history,
)

# The longest bar in the season chart, in columns.
BAR_WIDTH = 30


def _percent_colour(percent: int) -> str:
    """Green for a healthy cell, yellow for a part-used one, red for a nearly flat one."""
    if percent >= 70:
        return "green"
    return "yellow" if percent >= 40 else "bright_red"


def _coloured_percents(percents: list[int]) -> str:
    """The Reading cell, each cell's percentage coloured by how full it is."""
    return ", ".join(click.style(f"{p}%", fg=_percent_colour(p), bold=True) for p in percents)


def _on_low(battery: PastBattery) -> Lifespan | None:
    """How long a battery kept going once low; a minimum if it was replaced before dying."""
    if not (went_low := battery["went_low"]):
        return None  # taken out before it ever warned
    died = battery.get("died")
    end = date.fromisoformat(died or battery["replaced"])
    return {"days": (end - date.fromisoformat(went_low)).days, "minimum": not died}


def _format_on_low(battery: PastBattery) -> str:
    """The On low column: a dash for a set taken out before it ever warned."""
    on_low = _on_low(battery)
    return format_last([on_low]) if on_low else f"{NO_VALUE:>6}"


@click.command("battery-history")
@click.option(
    "--svg",
    "svg_path",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help="Also save the season chart as an SVG file.",
)
def battery_history_command(svg_path: Path | None):
    """Show every replaced battery and low warning, with averages."""
    history = load_battery_history()
    lifespans = [
        (serial, battery)
        for serial, entry in history.items()
        for battery in entry.get("past_batteries", [])
    ]
    lows = [
        (serial, period)
        for serial, entry in history.items()
        for period in entry.get("low_periods", [])
    ]
    lows += [
        (serial, period)
        for serial, battery in lifespans
        for period in battery.get("low_periods", [])
    ]
    readings: list[tuple[str, MeterReading, str | None]] = [
        (serial, r, None)
        for serial, entry in history.items()
        for r in entry.get("meter_readings", [])
    ]
    readings += [
        (serial, r, battery["replaced"])
        for serial, battery in lifespans
        for r in battery.get("meter_readings", [])
    ]

    if not lifespans and not lows and not readings:
        click.echo("No replaced batteries recorded yet.")
        return

    # Room names need the API; the history itself is local, so carry on without them.
    client = TadoClient()
    device_zones = device_zone_map(client) if client.connect() else {}

    if lifespans:
        _print_lifespans(lifespans, device_zones)
    if lows:
        _print_low_periods(lows, device_zones)
    if readings:
        _print_meter_readings(readings, device_zones)
    if svg_path:
        _save_season_svg([battery for _, battery in lifespans], svg_path)


def _save_season_svg(all_batteries: list[PastBattery], path: Path) -> None:
    """Write the season chart to an SVG file, or say why there's nothing to draw yet."""
    summaries, left_out = season_summaries(all_batteries)
    if longest_average(summaries) is None:
        click.echo(click.style("  No measured sets yet, so no season chart to save.", fg="yellow"))
        return
    try:
        path.write_text(season_svg(summaries, left_out), encoding="utf-8")
    except OSError as error:
        raise click.ClickException(f"Couldn't save the season chart: {error}") from error
    click.echo(f"  Season chart saved to {click.style(str(path), bold=True)}")


def _print_lifespans(lifespans: list[tuple[str, PastBattery]], device_zones: dict) -> None:
    """Print the table of replaced batteries and their averages."""
    rows = sorted(
        (
            (device_zones.get(serial, "Unassigned"), serial, battery)
            for serial, battery in lifespans
        ),
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
        f"{'On low':>6}  "
        "Make"
    )
    click.echo()
    echo_section("Replaced batteries", header)

    for zone, serial, battery in rows:
        went_low = battery["went_low"]
        click.echo(
            f"  {cell(zone, zone_width, **ZONE_STYLE)}  "
            f"{cell(serial, serial_width, **SERIAL_STYLE)}  "
            f"{battery['fitted']:<10}  "
            f"{cell(went_low or 'never', 10, **(LOW_STYLE if went_low else GOOD_STYLE))}  "
            f"{battery['replaced']:<10}  "
            f"{format_last([battery])}  "
            f"{_format_on_low(battery)}  "
            f"{cell(battery.get('make', ''), 0, **MAKE_STYLE)}".rstrip()
        )

    all_batteries = [battery for _, battery in lifespans]
    _print_lifespan_averages(all_batteries)
    _print_device_averages(rows, zone_width, serial_width)
    _print_make_averages(all_batteries)
    _print_season_averages(all_batteries)


def _print_lifespan_averages(all_batteries: list[PastBattery]) -> None:
    """Print the average lifespan, and how long a low battery keeps going."""
    # Average of the sets whose real lifespan we know
    measured = sum(1 for battery in all_batteries if not battery.get("minimum"))
    unknown = len(all_batteries) - measured
    average = average_days(all_batteries)

    click.echo()
    label = click.style("Average:", **SECTION_STYLE)
    if average is None:
        click.echo(
            f"  {label} " + click.style("none yet, every set so far is of unknown age", dim=True)
        )
    else:
        days = click.style(f"{average}d", fg=age_colour(average), bold=True)
        summary = f"  {label} {days} from {count(measured, 'set')}"
        if unknown:
            summary += click.style(f" ({unknown} of unknown age not counted)", fg="bright_black")
        click.echo(summary)

    # Only batteries that actually died tell us how long a low one keeps going
    on_low = [low for battery in all_batteries if (low := _on_low(battery))]
    low_average = average_days(on_low)
    if low_average is not None:
        died = sum(1 for battery in on_low if not battery["minimum"])
        label = click.style("Average on low:", **SECTION_STYLE)
        days = click.style(f"{low_average}d", fg=age_colour(low_average), bold=True)
        click.echo(f"  {label} {days} from {count(died, 'set')}")
    click.echo()


def _print_device_averages(
    rows: list[tuple[str, str, PastBattery]], zone_width: int, serial_width: int
) -> None:
    """Print each device's own average lifespan, for devices with a measured set."""
    by_device: dict[tuple[str, str], list[PastBattery]] = {}
    for zone, serial, battery in rows:
        by_device.setdefault((zone, serial), []).append(battery)
    averages = [
        (zone, serial, average)
        for (zone, serial), batteries in by_device.items()
        if (average := format_average(batteries)).strip()
    ]
    if not averages:
        return

    header = f"  {'Zone':<{zone_width}}  {'Serial':<{serial_width}}  {'Average':>8}"
    echo_section("Average by device", header)
    for zone, serial, average in averages:
        click.echo(
            f"  {cell(zone, zone_width, **ZONE_STYLE)}  "
            f"{cell(serial, serial_width, **SERIAL_STYLE)}  {average}"
        )
    click.echo()


def _print_make_averages(all_batteries: list[PastBattery]) -> None:
    """Print the average lifespan of each make, for makes with a measured set."""
    by_make: dict[str, list[PastBattery]] = {}
    for battery in all_batteries:
        if make := battery.get("make"):
            by_make.setdefault(make, []).append(battery)
    averages = [
        (make, average)
        for make, batteries in sorted(by_make.items(), key=lambda item: item[0].casefold())
        if (average := format_average(batteries)).strip()
    ]
    if not averages:
        return

    make_width = max(len("Make"), *(len(make) for make, _ in averages))
    header = f"  {'Make':<{make_width}}  {'Average':>8}"
    echo_section("Average by make", header)
    for make, average in averages:
        click.echo(f"  {cell(make, make_width, **MAKE_STYLE)}  {average}")
    click.echo()


def _print_season_averages(all_batteries: list[PastBattery]) -> None:
    """Print a bar per season fitted: a winter set works harder, so it can't match a summer one."""
    summaries, left_out = season_summaries(all_batteries)
    longest = longest_average(summaries)
    if longest is None:
        return

    header = f"  {'Season':<6}   {'Average days to first low':<{BAR_WIDTH}}  {'':>8}"
    echo_section("Average by season fitted", header)
    for summary in summaries:
        click.echo(f"  {cell(summary.season, 6, **ZONE_STYLE)}   {_season_bar(summary, longest)}")
    if needs_hint(summaries):
        click.echo(click.style(f"  {HINT}", fg="yellow"))
    if left_out:
        click.echo(click.style(f"  {left_out_note(left_out)}", dim=True))
    click.echo()


def _season_bar(summary: SeasonSummary, longest: int) -> str:
    """One season's bar, its average and set count, and the range when there are two or more."""
    if summary.average is None:
        return f"{'':<{BAR_WIDTH}}  " + click.style("none yet", dim=True)
    colour = age_colour(summary.average)
    drawn = cell(bar(summary.average, longest, BAR_WIDTH), BAR_WIDTH, fg=colour)
    figure = cell(f"{summary.average}d ×{len(summary.days)}", 8, ">", fg=colour, bold=True)
    line = f"{drawn}  {figure}"
    if len(summary.days) >= 2:
        line += click.style(f"   {summary.shortest}–{summary.longest}d", dim=True)
    return line


def _print_low_periods(lows: list[tuple[str, LowPeriod]], device_zones: dict) -> None:
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
        f"{'Last low':<10}  "
        f"{'Normal again':<12}  "
        f"{'Days':>6}"
    )
    echo_section("Low warnings", header)

    for zone, serial, period in rows:
        end = date.fromisoformat(period["to"]) if period["to"] else date.today()
        days = (end - date.fromisoformat(period["from"])).days
        still_low = period["to"] is None
        end_style = STILL_LOW_STYLE if still_low else GOOD_STYLE
        click.echo(
            f"  {cell(zone, zone_width, **ZONE_STYLE)}  "
            f"{cell(serial, serial_width, **SERIAL_STYLE)}  "
            f"{cell(period['from'], 10, **LOW_STYLE)}  "
            f"{cell(period.get('seen') or period['from'], 10, **LOW_STYLE)}  "
            f"{cell(period['to'] or 'still low', 12, **end_style)}  "
            f"{cell(f'{days}d', 6, '>', **(STILL_LOW_STYLE if still_low else {}))}"
        )
    click.echo()


def _print_meter_readings(
    readings: list[tuple[str, MeterReading, str | None]], device_zones: dict
) -> None:
    """Print every battery meter reading taken, oldest first, with whether that set of
    batteries is still in (replaced is None) or when it came out, since a note written
    at the time ("left in for now") can't say what happened next."""
    rows = sorted(
        (
            (device_zones.get(serial, "Unassigned"), serial, reading, replaced)
            for serial, reading, replaced in readings
        ),
        key=lambda row: (row[2]["date"], row[0]),
    )
    zone_width = max(len("Zone"), *(len(row[0]) for row in rows))
    serial_width = max(len("Serial"), *(len(row[1]) for row in rows))
    percents = [format_percents(row[2]["percent"]) for row in rows]
    percent_width = max(len("Reading"), *(len(p) for p in percents))
    fates = [f"out {row[3]}" if row[3] else "still in" for row in rows]
    fate_width = max(len("Batteries"), *(len(f) for f in fates))

    header = (
        f"  {'Zone':<{zone_width}}  {'Serial':<{serial_width}}  "
        f"{'Date':<10}  {'Reading':<{percent_width}}  {'Batteries':<{fate_width}}  Note"
    )
    echo_section("Meter readings", header)
    for (zone, serial, reading, replaced), percent, fate in zip(rows, percents, fates):
        click.echo(
            f"  {cell(zone, zone_width, **ZONE_STYLE)}  "
            f"{cell(serial, serial_width, **SERIAL_STYLE)}  {reading['date']:<10}  "
            f"{_coloured_percents(reading['percent'])}{' ' * (percent_width - len(percent))}  "
            f"{cell(fate, fate_width, **(SERIAL_STYLE if replaced else GOOD_STYLE))}  "
            f"{reading.get('note', '')}".rstrip()
        )
    click.echo()
