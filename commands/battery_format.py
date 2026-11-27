"""
Formatting shared by the battery report, the history and the commands that
record batteries: age colours, lifespans, averages and readings.
"""

from collections.abc import Sequence
from typing import Any

import click

from core.battery_seasons import age_band
from core.storage import Lifespan

# Colour bands for battery age, one per 100 days. Bright colours for a black background.
AGE_BANDS = ["bright_green", "bright_cyan", "bright_yellow", "bright_magenta", "bright_red"]


# Shown in a table cell that has nothing to show.
NO_VALUE = "—"

# Colours for the battery tables: one per kind of value, so each column reads at a glance.
ZONE_STYLE: dict[str, Any] = {"bold": True}
SERIAL_STYLE: dict[str, Any] = {"fg": "bright_black"}
LOW_STYLE: dict[str, Any] = {"fg": "yellow"}
STILL_LOW_STYLE: dict[str, Any] = {"fg": "bright_red", "bold": True}
GOOD_STYLE: dict[str, Any] = {"fg": "green"}
MAKE_STYLE: dict[str, Any] = {"fg": "bright_blue"}


def age_colour(days: int) -> str:
    """Pick a colour for a battery age, changing every 100 days."""
    return AGE_BANDS[age_band(days)]


def format_last(past_batteries: Sequence[Lifespan]) -> str:
    """Format how long the previous battery lasted, marking unknown-age ones as a minimum."""
    if not past_batteries:
        return f"{'':>6}"
    last = past_batteries[-1]
    label = f"≥{last['days']}d" if last.get("minimum") else f"{last['days']}d"
    return click.style(f"{label:>6}", fg=age_colour(last["days"]), bold=True)


def average_days(lifespans: Sequence[Lifespan]) -> int | None:
    """Average the measured lifespans, leaving out unknown-age minimums."""
    measured = [b["days"] for b in lifespans if not b.get("minimum")]
    if not measured:
        return None
    return round(sum(measured) / len(measured))


def format_average(past_batteries: Sequence[Lifespan]) -> str:
    """The Average column: mean measured lifespan and how many sets, e.g. "205d ×2"."""
    average = average_days(past_batteries)
    if average is None:
        return " " * 8
    measured = sum(1 for b in past_batteries if not b.get("minimum"))
    label = f"{average}d ×{measured}"
    return click.style(f"{label:>8}", fg=age_colour(average), bold=True)


def format_percents(percents: list[int]) -> str:
    """ "50%, 40%": one meter reading per cell."""
    return ", ".join(f"{p}%" for p in percents)
