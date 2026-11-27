"""
The commands that record what was done to the batteries: replaced, their make,
and a meter reading.
"""

from datetime import date

import click

from commands.battery_format import format_percents
from commands.device_lookup import complete_device, resolve_device
from core.storage import (
    AlreadyReplacedToday,
    BatteryHistory,
    NoOldBatteries,
    PastBattery,
    add_meter_reading,
    known_makes,
    load_battery_history,
    mark_battery_replaced,
    replaced_today,
    set_battery_make,
)


@click.command("battery-replaced")
@click.argument("device", shell_complete=complete_device)
@click.option("--make", help="Make of the new AA batteries. Asked for if not given.")
@click.option(
    "--old-make",
    help="Make of the batteries taken out. Asked for only if it wasn't recorded already.",
)
def battery_replaced_command(device, make, old_make):
    """Record that you have replaced the batteries in DEVICE (a serial, or a room
    name, roughly).

    It asks for the make of the new batteries and, if it isn't known, of the
    old ones. Press Enter to skip either.

    If you measured the old batteries, record that first with battery-reading,
    and it moves across with them:

    \b
      tado battery-reading loo 50 50 --note "changed early"
      tado battery-replaced loo

    Forgot? Add it afterwards with battery-reading --old-set.
    """
    serial = resolve_device(device, "Record new batteries in")
    history = load_battery_history()
    if serial not in history:
        raise click.ClickException(f"No battery history for {serial}.")
    if replaced_today(history[serial]):
        click.echo(f"{serial} was already marked as replaced today; nothing changed.")
        return

    _echo_known_makes(history, make, old_make)
    if make is None:
        make = _ask_make("Make of the new batteries")
    if old_make is None and not history[serial].get("make"):
        old_make = _ask_make("Make of the batteries taken out")

    try:
        retired = mark_battery_replaced(serial, make=make, old_make=old_make)
    except AlreadyReplacedToday:
        click.echo(f"{serial} was already marked as replaced today; nothing changed.")
        return
    click.echo(f"{serial} marked as replaced. {_describe_retired(retired)}")


def _echo_known_makes(history: BatteryHistory, make: str | None, old_make: str | None) -> None:
    """List the makes used before, if a make is about to be asked for."""
    if make is not None and old_make is not None:
        return
    if makes := known_makes(history):
        click.echo(click.style("Makes recorded so far: ", fg="bright_black") + ", ".join(makes))


def _ask_make(question: str) -> str:
    """Ask for a battery make; a blank answer means not known."""
    return click.prompt(
        f"{question} (Enter to skip)", default="", show_default=False, type=str
    ).strip()


@click.command("battery-make")
@click.argument("device", shell_complete=complete_device)
@click.argument("make")
@click.option(
    "--old-set",
    is_flag=True,
    help="Put the make on the batteries last taken out, not the ones now fitted.",
)
def battery_make_command(device, make, old_set):
    """Record or correct the MAKE of the batteries in DEVICE (a serial, or a room
    name, roughly).

    battery-replaced asks for the make, so this is for one missed or mistyped:

    \b
      tado battery-make loo Duracell
      tado battery-make loo Energizer --old-set
    """
    serial = resolve_device(device, f"Record {make} batteries in")
    try:
        saved, replaced = set_battery_make(serial, make, old_set=old_set)
    except KeyError:
        raise click.ClickException(f"No battery history for {serial}.")
    except NoOldBatteries:
        raise click.ClickException(f"{serial} has no replaced batteries to add a make to.")
    except ValueError:
        raise click.BadParameter("can't be blank.", param_hint="MAKE")

    message = f"{serial}: {saved} recorded"
    if replaced:
        message += f" for the batteries taken out on {replaced}"
    click.echo(message + ".")


def _describe_retired(retired: PastBattery | None) -> str:
    """Say what was kept of the batteries just taken out."""
    if retired is None:
        return "The old set's dates were unusable, so no lifespan was saved."
    if retired["went_low"] is None:
        return (
            f"The old set never gave a low warning; it was in for {retired['days']} days, "
            "saved as a minimum lifespan."
        )
    prefix = "at least " if retired["minimum"] else ""
    return f"The old set reached its low warning after {prefix}{retired['days']} days."


@click.command("battery-reading")
@click.argument("device", shell_complete=complete_device)
@click.argument("percents", nargs=-1, required=True, type=click.IntRange(0, 100))
@click.option(
    "--date",
    "on",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Day of the reading (YYYY-MM-DD). Defaults to today.",
)
@click.option("--note", help="Anything worth keeping, such as whether the batteries went back in.")
@click.option(
    "--old-set",
    is_flag=True,
    help="Put the reading on the batteries last taken out, not the ones now fitted. "
    "The date defaults to the day they came out.",
)
def battery_reading_command(device, percents, on, note, old_set):
    """Record a battery meter's reading, one PERCENT per cell, for DEVICE (a
    serial, or a room name, roughly).

    The reading belongs to the batteries now in the device. When changing
    batteries, record the old ones' reading before battery-replaced, and it
    moves across with them. Already run battery-replaced? Then --old-set puts
    it on the batteries you took out:

    \b
      tado battery-reading loo 50 50 --old-set --note "changed early"
    """
    if on and on.date() > date.today():
        raise click.BadParameter("can't be in the future.", param_hint="--date")
    serial = resolve_device(device, f"Record {format_percents(list(percents))} for")
    try:
        reading, replaced = add_meter_reading(
            serial,
            list(percents),
            on=on.date().isoformat() if on else None,
            note=note,
            old_set=old_set,
        )
    except KeyError:
        raise click.ClickException(f"No battery history for {serial}.")
    except NoOldBatteries:
        raise click.ClickException(f"{serial} has no replaced batteries to add a reading to.")

    message = f"{serial}: {format_percents(reading['percent'])} recorded for {reading['date']}"
    if replaced:
        message += f", on the batteries taken out on {replaced}"
    click.echo(message + ".")
