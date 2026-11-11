"""
Decide which heat-check faults to notify.

A new fault is notified straight away. One that carries on is notified again
once a week, so a known problem isn't forgotten, and a fault that has gone is
notified once as cleared. Findings are still logged every day; this only
decides what reaches a notification.
"""

from datetime import date, timedelta

REPEAT_AFTER = timedelta(days=7)

_FOUND = {
    "warming": "{zone} warmed with the heating off",
    "offline": "{zone} is offline",
}
_CLEARED = {
    "warming": "{zone} has stopped warming with the heating off",
    "offline": "{zone} is back online",
}


def update_faults(faults: dict, day: date, current: dict[str, tuple[str, str]]) -> tuple[dict, list[str]]:
    """
    Apply one checked day's faults to the known ones.

    current: {"<zone_id>:<kind>": (zone_name, kind)} for the faults found on `day`.
    Returns the new faults and the lines to notify. The input isn't changed.
    """
    today = day.isoformat()
    updated = {}
    lines = []

    for key, (zone, kind) in current.items():
        known = faults.get(key)
        if known is None:
            updated[key] = {"zone": zone, "kind": kind, "first_seen": today, "last_seen": today, "last_notified": today}
            lines.append(_FOUND[kind].format(zone=zone))
            continue
        record = {**known, "zone": zone, "last_seen": today}
        if day - date.fromisoformat(known["last_notified"]) >= REPEAT_AFTER:
            record["last_notified"] = today
            lines.append(_FOUND[kind].format(zone=zone))
        updated[key] = record

    for key, known in faults.items():
        if key not in current:
            lines.append(_CLEARED[known["kind"]].format(zone=known["zone"]))

    return updated, lines
