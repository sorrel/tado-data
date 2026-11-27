"""
Heat check: find rooms that warmed with no call for heat, and offline valves.

Run by hand it reports one day. With --scheduled (from launchd each morning)
it checks every day since the last check, and notifies on this Mac only when
there is something to say: a new fault, a known one once a week, a cleared
one, or the check itself failing. It never prompts for a login.

The scheduled run also checks the batteries once a day, saving what it sees
to the battery history as `tado battery` does, and notifies only a change:
a device going LOW, back to NORMAL, offline while LOW, or back online.
"""

from datetime import date, datetime, timedelta

import click

from tado_data.core.auth import AuthError, AuthNetworkError, LoginNeeded, TokenLockBusy
from tado_data.core.battery_alerts import battery_changes
from tado_data.core.battery_devices import (
    BatteryDevice,
    battery_devices,
    device_rooms,
    record_battery_states,
)
from tado_data.core.client import RateLimited, TadoAPIError, TadoClient
from tado_data.core.heat_alerts import update_faults
from tado_data.core.heat_detect import LONDON, Finding, Offline, Warming, find_problems
from tado_data.core.heat_store import load_day_report, load_state, save_day_report, save_state
from tado_data.core.jsonfile import DamagedFile
from tado_data.core.notify import NotifyError, notify
from tado_data.core.storage import load_battery_history

TITLE = "Tado heat check"
MAX_CATCH_UP = 7


class HomeNotFound(Exception):
    """Logged in, but Tado's account details named no home."""


class NoHeatingZones(Exception):
    """Tado listed no heating zones, so there was nothing to check."""


def days_to_check(today: date, last_checked: date | None) -> tuple[list[date], list[date]]:
    """(days to check, oldest first; days skipped as older than MAX_CATCH_UP)."""
    yesterday = today - timedelta(days=1)
    if last_checked is None:
        return [yesterday], []
    earliest = today - timedelta(days=MAX_CATCH_UP)
    due = [last_checked + timedelta(days=n) for n in range(1, (yesterday - last_checked).days + 1)]
    return [d for d in due if d >= earliest], [d for d in due if d < earliest]


def _heating(zones: list[dict]) -> list[dict]:
    return [zone for zone in zones if zone.get("type") == "HEATING"]


def check_day(client, day: date, zones: list[dict]) -> dict[int, list[Finding]]:
    """Findings for each heating zone, using saved reports and saving any fetched."""
    found = {}
    for zone in _heating(zones):
        report = load_day_report(day, zone["id"])
        if report is None:
            report = client.get_day_report(zone["id"], day)
            if day < date.today():  # a report for today is incomplete
                save_day_report(day, zone["id"], report)
        found[zone["id"]] = find_problems(report, day)
    return found


def _local(when: datetime) -> str:
    return when.astimezone(LONDON).strftime("%H:%M")


def format_finding(finding: Finding) -> str:
    match finding:
        case Warming(start, end, rise, low, high):
            return (
                f"warmed {rise:.1f}° ({low:.1f}° → {high:.1f}°) "
                f"between {_local(start)} and {_local(end)} with no call for heat"
            )
        case Offline(start):
            return f"offline from {_local(start)}"


def _names(zones: list[dict]) -> dict[int, str]:
    return {zone["id"]: zone.get("name", f"Zone {zone['id']}") for zone in _heating(zones)}


# --- scheduled run ------------------------------------------------------------


def _log(message: str) -> None:
    click.echo(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {message}")


def _failure_message(error: Exception) -> str:
    if isinstance(error, LoginNeeded):
        return "Heat check didn't run: Tado login has expired. Run tado auth."
    if isinstance(error, AuthNetworkError):
        return "Heat check didn't run: couldn't reach Tado's login server."
    if isinstance(error, TokenLockBusy):
        return (
            "Heat check didn't run: another tado command was using the login. "
            "It will try again tomorrow."
        )
    if isinstance(error, RateLimited):
        return "Tado's daily request limit was reached; the check will carry on tomorrow."
    if isinstance(error, TadoAPIError):
        reason = f"({error.status})" if error.status else "(couldn't reach Tado)"
        return f"Heat check didn't run: Tado returned an error {reason}."
    if isinstance(error, HomeNotFound):
        return "Heat check didn't run: Tado didn't say which home to check."
    if isinstance(error, NoHeatingZones):
        return "Heat check didn't run: Tado listed no heating zones."
    if isinstance(error, DamagedFile):
        return "Heat check didn't run: a saved file is damaged. See the log."
    return "Heat check didn't run: unexpected error. See the log."


def _send(message: str) -> bool:
    try:
        notify(TITLE, message)
        return True
    except NotifyError as error:
        click.echo(f"Couldn't show the notification: {error}", err=True)
        click.echo(f"It said: {message}", err=True)
        return False


def _connect() -> TadoClient:
    client = TadoClient()
    if not client.connect(interactive=False):
        raise HomeNotFound("no home ID")
    return client


def _scheduled_check(today: date, lines: list[str]) -> None:
    """Check every due day and the batteries, saving state after each; adds to `lines`."""
    state = load_state()
    last = date.fromisoformat(state["last_checked"]) if state["last_checked"] else None
    days, skipped = days_to_check(today, last)
    for day in skipped:
        _log(f"{day}: not checked, more than {MAX_CATCH_UP} days ago")
    battery_due = state["battery_checked"] != today.isoformat()
    if not days and not battery_due:
        _log("Nothing to check.")
        return

    client = _connect()
    zones = client.get_zones(strict=True) or []  # strict: a failure raises rather than None
    if days:
        state = _check_days(client, days, zones, state, lines)
    if battery_due:
        lines.extend(_check_batteries(client, zones))
        state = {**state, "battery_checked": today.isoformat()}
        save_state(state)

    if client.rate_limit:
        _log(f"Rate limit: {client.rate_limit}")


def _check_days(client, days: list[date], zones: list[dict], state: dict, lines: list[str]) -> dict:
    """Check each day in turn, saving state after each. Returns the new state."""
    names = _names(zones)
    if not names:
        raise NoHeatingZones("no heating zones")
    for day in days:
        found = check_day(client, day, zones)
        current = {}
        for zone_id, findings in found.items():
            for finding in findings:
                _log(f"{day}: {names[zone_id]} {format_finding(finding)}")
                current[f"{zone_id}:{finding.kind}"] = (names[zone_id], finding.kind)
        if not current:
            _log(f"{day}: no problems")
        faults, new_lines = update_faults(state["faults"], day, current)
        state = {**state, "last_checked": day.isoformat(), "faults": faults}
        save_state(state)
        lines.extend(new_lines)
    return state


def _device_label(device: BatteryDevice) -> str:
    kind = "valve" if device.type.startswith("VA") else "thermostat"
    return f"{device.zone} {kind}"


def _check_batteries(client, zones: list[dict]) -> list[str]:
    """Save today's battery states to the history; the changes to notify."""
    devices = battery_devices(client.get_devices(strict=True) or [], device_rooms(zones))
    before = load_battery_history()
    after = record_battery_states(devices)
    for device in devices:
        if not device.mains:
            online = "online" if device.connected else "offline"
            _log(f"Battery: {_device_label(device)} {device.serial} {device.battery}, {online}")
    labels = {device.serial: _device_label(device) for device in devices}
    changes = battery_changes(before, after, labels)
    if not changes:
        _log("Batteries: no change")
    return changes


def _run_scheduled(today: date) -> int:
    lines: list[str] = []
    try:
        _scheduled_check(today, lines)
    except Exception as error:
        _log(f"Failed: {error!r}")
        _send("; ".join([_failure_message(error), *lines]))
        expected = (AuthError, TadoAPIError, HomeNotFound, NoHeatingZones, DamagedFile)
        if not isinstance(error, expected):
            raise  # the traceback goes to the log
        return 1  # whether or not the notification showed, the check failed
    if lines:
        _log("Notifying: " + "; ".join(lines))
        if not _send("; ".join(lines)):
            return 1
    return 0


# --- the command ----------------------------------------------------------------


@click.command("heat-check")
@click.option(
    "--date",
    "on",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Day to check (YYYY-MM-DD). Defaults to yesterday.",
)
@click.option(
    "--scheduled",
    is_flag=True,
    help="Run unattended: check every day since the last run and notify.",
)
@click.pass_context
def heat_check_command(ctx, on, scheduled):
    """Find rooms that warmed with no call for heat, and offline valves."""
    today = date.today()
    if scheduled:
        if on:
            raise click.UsageError("--date can't be used with --scheduled.")
        ctx.exit(_run_scheduled(today))

    day = on.date() if on else today - timedelta(days=1)
    if day >= today:
        raise click.BadParameter(
            "must be before today; today's report isn't complete yet.", param_hint="--date"
        )

    client = TadoClient()
    if not client.connect():
        ctx.exit(1)
    zones = client.get_zones()
    if not zones:
        raise click.ClickException("No zones found.")
    try:
        found = check_day(client, day, zones)
    except RateLimited:
        raise click.ClickException(
            "Tado's daily request limit has been reached. Try again tomorrow."
        )
    except TadoAPIError as error:
        raise click.ClickException(f"Tado returned an error: {error}.")

    names = _names(zones)
    rows = [
        (names[zone_id], finding) for zone_id, findings in found.items() for finding in findings
    ]
    if not rows:
        click.echo(f"No problems on {day}")
        return
    width = max(len(name) for name, _ in rows)
    for name, finding in rows:
        click.echo(f"  {name:<{width}}  {format_finding(finding)}")
