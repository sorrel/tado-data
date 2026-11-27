"""
Finding a device from what is typed: a serial, or a rough room name.

Used by the commands that record batteries, and by tab completion, which
must never contact Tado.
"""

import difflib
import re

import click
from click.shell_completion import CompletionItem

from core.battery_devices import MAINS_WIRED_SERIALS, device_rooms
from core.client import TadoClient
from core.storage import BatteryHistory, load_battery_history, load_room_names


def device_zone_map(client: TadoClient) -> dict[str, str]:
    """Fetch the zones and map each device's serial to its zone's name."""
    return device_rooms(client.get_zones() or [])


# A Tado serial: two letters then digits, such as VA0149052928. Anything else is a room name.
SERIAL_PATTERN = re.compile(r"^[A-Za-z]{2}\d+$")


def _squash(text: str) -> str:
    """Lower-case and drop spaces and punctuation, so "downstairs-loo" finds "Downstairs Loo"."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def match_rooms(query: str, rooms: list[str]) -> tuple[list[str], bool]:
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


def complete_device(ctx, param, incomplete: str) -> list[CompletionItem]:
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
    rooms = _rooms_with_batteries(history, room_names)
    wanted = _squash(incomplete)

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


def _rooms_with_batteries(history: BatteryHistory, room_of: dict[str, str]) -> dict[str, list[str]]:
    """Group the battery devices in HISTORY by room, using a serial-to-room map."""
    rooms: dict[str, list[str]] = {}
    for serial, room in sorted(room_of.items()):
        if serial in history and serial not in MAINS_WIRED_SERIALS:
            rooms.setdefault(room, []).append(serial)
    return rooms


def _label_if_low(serial: str, history: BatteryHistory) -> str:
    """The serial, marked "(low)" while its batteries are low, to help pick between two."""
    periods = history[serial].get("low_periods", [])
    return f"{serial} (low)" if periods and periods[-1].get("to") is None else serial


def resolve_device(name: str, action: str) -> str:
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
        raise click.ClickException(
            "Couldn't reach Tado to look up room names. Use the device's serial instead."
        )
    rooms = _rooms_with_batteries(history, device_zone_map(client))

    found, close_only = match_rooms(name, sorted(rooms))
    if not found:
        raise click.ClickException(
            f'No room matches "{name}". Rooms with battery devices: {", ".join(sorted(rooms))}.'
        )
    if len(found) > 1:
        raise click.ClickException(f'"{name}" could be {", ".join(found)}. Be more specific.')

    room = found[0]
    serials = rooms[room]
    if len(serials) > 1:
        labels = ", ".join(_label_if_low(serial, history) for serial in serials)
        raise click.ClickException(
            f"{room} has {len(serials)} battery devices: {labels}. Give the serial instead."
        )

    serial = serials[0]
    if close_only:
        click.confirm(f"{action} {room} ({serial})?", default=True, abort=True)
    else:
        click.echo(f"{room}: {serial}")
    return serial
