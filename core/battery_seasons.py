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


# --- Footnotes, shared by the terminal chart and the SVG --------------------

HINT = "Fewer than 3 sets in a season: read it as a hint, not a result."


def needs_hint(summaries: Sequence[SeasonSummary]) -> bool:
    """True while any season's figure rests on only one or two sets."""
    return any(0 < len(s.days) < 3 for s in summaries)


def left_out_note(left_out: int) -> str:
    """ "1 set not counted: …", "3 sets not counted: …"."""
    sets = f"{left_out} set{'s' if left_out != 1 else ''}"
    return f"{sets} not counted: unknown age, or taken out before they warned."


def longest_average(summaries: Sequence[SeasonSummary]) -> int | None:
    """The average the bars are scaled to; None while no season has a measured set."""
    return max((s.average for s in summaries if s.average), default=None)


# --- Colours ----------------------------------------------------------------

# The terminal's age bands (green, cyan, yellow, magenta, red) as hex, for the SVG.
AGE_HEX: tuple[str, ...] = ("#4ade80", "#22d3ee", "#facc15", "#e879f9", "#f87171")


def age_band(days: int) -> int:
    """Which colour band a lifespan falls in, one per 100 days."""
    return min(days // 100, len(AGE_HEX) - 1)


# --- SVG --------------------------------------------------------------------

_SVG_WIDTH = 640
_BAR_X, _BAR_MAX = 110, 360
_FIGURE_X = _BAR_X + _BAR_MAX + 70  # right edge of "212d ×3"
_FIRST_ROW, _ROW_GAP, _NOTE_GAP = 78, 36, 22
_BACKGROUND, _TEXT, _DIM, _TRACK = "#1e1e1e", "#f5f5f5", "#8a8a8a", "#2a2a2a"
_TITLE, _HINT_COLOUR = "#67e8f9", "#facc15"


def _text(x: float, y: float, content: str, fill: str, **attributes: str) -> str:
    extra = "".join(f' {name.replace("_", "-")}="{value}"' for name, value in attributes.items())
    return f'<text x="{x}" y="{y}" fill="{fill}"{extra}>{content}</text>'


def _rect(kind: str, y: int, width: float, fill: str) -> str:
    """A bar or its track, centred on row y, with rounded ends."""
    return (
        f'<rect class="{kind}" x="{_BAR_X}" y="{y - 10}" width="{width}" height="20" '
        f'rx="4" fill="{fill}"/>'
    )


def _svg_open(height: int) -> str:
    """The opening tag: fixed size, with a viewBox so it scales."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_SVG_WIDTH}" height="{height}" '
        f'viewBox="0 0 {_SVG_WIDTH} {height}" '
        'font-family="-apple-system, system-ui, Helvetica, sans-serif" font-size="15">'
    )


def _svg_row(summary: SeasonSummary, longest: int, y: int) -> list[str]:
    """One season: its name, a faint track, the bar, the figure and the range."""
    parts = [
        _text(24, y + 5, summary.season, _TEXT, font_weight="600"),
        _rect("track", y, _BAR_MAX, _TRACK),
    ]
    if summary.average is None:
        parts.append(_text(_FIGURE_X, y + 5, "none yet", _DIM, text_anchor="end"))
        return parts
    colour = AGE_HEX[age_band(summary.average)]
    width = round(summary.average / longest * _BAR_MAX, 1)
    parts += [
        _rect("bar", y, width, colour),
        _text(
            _FIGURE_X,
            y + 5,
            f"{summary.average}d ×{len(summary.days)}",
            colour,
            font_weight="700",
            text_anchor="end",
        ),
    ]
    if len(summary.days) >= 2:
        parts.append(_text(_FIGURE_X + 14, y + 5, f"{summary.shortest}–{summary.longest}d", _DIM))
    return parts


def season_svg(summaries: list[SeasonSummary], left_out: int) -> str:
    """The season chart as a self-contained SVG on a dark card, matching the terminal."""
    longest = longest_average(summaries) or 1
    body = [
        _text(
            24,
            40,
            "Average days to first low, by season fitted",
            _TITLE,
            font_size="17",
            font_weight="700",
        )
    ]
    y = _FIRST_ROW
    for summary in summaries:
        body += _svg_row(summary, longest, y)
        y += _ROW_GAP
    notes = [(HINT, _HINT_COLOUR)] if needs_hint(summaries) else []
    if left_out:
        notes.append((left_out_note(left_out), _DIM))
    y += 4
    for note, colour in notes:
        body.append(_text(24, y, note, colour, font_size="13"))
        y += _NOTE_GAP
    height = y + 8
    return "\n".join(
        [
            _svg_open(height),
            f'<rect width="{_SVG_WIDTH}" height="{height}" rx="12" fill="{_BACKGROUND}"/>',
            *body,
            "</svg>",
            "",
        ]
    )
