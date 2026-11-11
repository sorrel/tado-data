"""
Find heating problems in one zone's Tado day report.

Pure logic: takes the parsed report, returns findings. Two kinds:

- warming: the room warmed by RISE_THRESHOLD or more while Tado wasn't asking
  for heat. A valve that can't close (as the Downstairs Loo's couldn't in
  November 2026) heats its room whenever the boiler fires for another.
- offline: the zone's measuring device was out of contact for MIN_OFFLINE or
  more in total during the day.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")

RISE_THRESHOLD = 2.0  # °C

# Heat already in the radiator keeps arriving after a call for heat ends.
# Checked against the 10 November 2026 loo report: flagged at 6.6° with
# 30 minutes (7.3° with none), so 30 minutes loses nothing on a real fault.
CARRY_OVER = timedelta(minutes=30)

MIN_OFFLINE = timedelta(hours=1)


@dataclass(frozen=True)
class Finding:
    kind: str  # "warming" | "offline"
    start: datetime  # warming: time of the low point; offline: first moment offline in the day
    end: datetime | None  # warming: time of the high point; offline: None
    rise: float | None = None
    low: float | None = None
    high: float | None = None


def day_window(day: date) -> tuple[datetime, datetime]:
    """Local midnight to the next local midnight, so 23 or 25 hours when the clocks change."""
    # In UTC: arithmetic between two times in the same zone is wall-clock
    # arithmetic in Python, which would make every day 24 hours long
    start = datetime.combine(day, time(), tzinfo=LONDON).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(), tzinfo=LONDON).astimezone(timezone.utc)
    return start, end


def _when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _series(report: dict, *path: str) -> dict:
    """The series at `path`, or {} if any level is missing or null (as Tado sends for a dead device)."""
    series = report
    for key in path:
        series = series.get(key) if isinstance(series, dict) else None
    return series if isinstance(series, dict) else {}


def _intervals(report: dict, *path: str) -> list[tuple[datetime, datetime, object]]:
    intervals = _series(report, *path).get("dataIntervals") or []
    return [(_when(i["from"]), _when(i["to"]), i.get("value")) for i in intervals]


def _temperatures(report: dict) -> list[tuple[datetime, float]]:
    points = []
    for point in _series(report, "measuredData", "insideTemperature").get("dataPoints") or []:
        celsius = (point.get("value") or {}).get("celsius")
        if celsius is not None:
            points.append((_when(point["timestamp"]), celsius))
    return sorted(points)


def _warming(report: dict, day_start: datetime, day_end: datetime) -> list[Finding]:
    points = _temperatures(report)
    found = []
    for spell_from, spell_to, value in _intervals(report, "callForHeat"):
        if value != "NONE":
            continue
        start = max(spell_from + CARRY_OVER, day_start)
        end = min(spell_to, day_end)
        lowest = None
        best = None  # (rise, low point, high point)
        for when, celsius in points:
            if not start <= when < end:
                continue
            if lowest is None or celsius < lowest[1]:
                lowest = (when, celsius)
            rise = celsius - lowest[1]
            if best is None or rise > best[0]:
                best = (rise, lowest, (when, celsius))
        if best and best[0] >= RISE_THRESHOLD:
            rise, (low_at, low), (high_at, high) = best
            found.append(Finding("warming", low_at, high_at, round(rise, 2), low, high))
    return sorted(found, key=lambda f: f.start)


def _offline(report: dict, day_start: datetime, day_end: datetime) -> list[Finding]:
    total = timedelta()
    first = None
    for spell_from, spell_to, connected in _intervals(report, "measuredData", "measuringDeviceConnected"):
        if connected is not False:
            continue
        start, end = max(spell_from, day_start), min(spell_to, day_end)
        if end <= start:
            continue
        total += end - start
        first = start if first is None else min(first, start)
    if first is not None and total >= MIN_OFFLINE:
        return [Finding("offline", first, None)]
    return []


def find_problems(report: dict, day: date) -> list[Finding]:
    """Warming findings first, in time order, then offline."""
    day_start, day_end = day_window(day)
    return _warming(report, day_start, day_end) + _offline(report, day_start, day_end)
