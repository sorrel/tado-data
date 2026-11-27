"""Battery lifespans grouped by the season the batteries were fitted, and the bars that draw them.

A valve works far harder in winter than in summer, so a set's lifespan depends on
when it went in. Seasons are the UK meteorological ones. Pure: no Click, no files.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from core.storage import PastBattery

SEASONS: tuple[str, ...] = ("Spring", "Summer", "Autumn", "Winter")

# The part of a block a bar ends on, in eighths: index 0 is one eighth.
_PARTIAL_BLOCKS = "▏▎▍▌▋▊▉"


def season_of(fitted: str) -> str:
    """The meteorological season of an ISO date. Raises ValueError for a non-date."""
    month = date.fromisoformat(fitted).month
    return SEASONS[(month % 12) // 3 - 1]  # Dec–Feb land on -1, Winter


@dataclass(frozen=True)
class SeasonSummary:
    """The measured lifespans of the sets fitted in one season."""

    season: str
    days: tuple[int, ...]

    @property
    def average(self) -> int | None:
        return round(sum(self.days) / len(self.days)) if self.days else None

    @property
    def shortest(self) -> int | None:
        return min(self.days, default=None)

    @property
    def longest(self) -> int | None:
        return max(self.days, default=None)


def _is_measured(battery: PastBattery) -> bool:
    """A set whose whole time to first low is known, as the other averages count it."""
    return not battery.get("minimum") and battery.get("went_low") is not None


def season_summaries(batteries: Sequence[PastBattery]) -> tuple[list[SeasonSummary], int]:
    """One summary per season, in SEASONS order, and how many sets were left out."""
    by_season: dict[str, list[int]] = {season: [] for season in SEASONS}
    left_out = 0
    for battery in batteries:
        try:
            season = season_of(battery["fitted"])
        except ValueError:
            season = None
        if season is None or not _is_measured(battery):
            left_out += 1
            continue
        by_season[season].append(battery["days"])
    return [SeasonSummary(season, tuple(days)) for season, days in by_season.items()], left_out


def bar(value: int, longest: int, width: int = 30) -> str:
    """A bar of eighth-blocks, `width` long for `longest`; never empty for a positive value."""
    eighths = max(1, round(value / longest * width * 8))
    full, rest = divmod(eighths, 8)
    return "█" * full + (_PARTIAL_BLOCKS[rest - 1] if rest else "")
