"""
Formatting shared by the battery commands: age colours, lifespans and averages.

No test reaches Tado: a fake client stands in, per CLAUDE.md.
"""

import click
import pytest

from tado_data.commands.battery_format import (
    AGE_BANDS,
    age_colour,
    average_days,
    format_average,
    format_last,
)


@pytest.mark.parametrize(
    "days,expected",
    [
        (0, "bright_green"),
        (99, "bright_green"),
        (100, "bright_cyan"),  # band boundary
        (199, "bright_cyan"),
        (250, "bright_yellow"),
        (300, "bright_magenta"),
        (400, "bright_red"),
    ],
)
def test_age_colour_changes_every_hundred_days(days, expected):
    assert age_colour(days) == expected


def test_age_colour_clamps_at_the_last_band():
    """Very old batteries stay red rather than running off the end."""
    assert age_colour(5000) == AGE_BANDS[-1]
    assert age_colour(100_000) == AGE_BANDS[-1]


def test_format_last_is_blank_with_no_past_batteries():
    assert click.unstyle(format_last([])) == " " * 6


def test_format_last_shows_a_measured_lifespan():
    assert click.unstyle(format_last([{"days": 204, "minimum": False}])) == "  204d"


def test_format_last_marks_a_minimum():
    assert click.unstyle(format_last([{"days": 210, "minimum": True}])) == " ≥210d"


def test_format_last_uses_the_most_recent_battery():
    past = [{"days": 90, "minimum": False}, {"days": 204, "minimum": False}]

    assert click.unstyle(format_last(past)) == "  204d"


def test_format_average_is_blank_with_no_past_batteries():
    assert click.unstyle(format_average([])) == " " * 8


def test_format_average_is_blank_when_every_set_is_of_unknown_age():
    """A minimum isn't a lifespan, so there is nothing to average yet."""
    past = [{"days": 209, "minimum": True}]

    assert click.unstyle(format_average(past)) == " " * 8


def test_format_average_shows_the_mean_and_how_many_sets():
    past = [
        {"days": 200, "minimum": False},
        {"days": 209, "minimum": True},
        {"days": 210, "minimum": False},
    ]

    assert click.unstyle(format_average(past)) == " 205d ×2"


def test_average_leaves_out_unknown_age_batteries():
    """A minimum isn't a real lifespan, so it would drag the average down."""
    lifespans = [
        {"days": 200, "minimum": False},
        {"days": 100, "minimum": False},
        {"days": 999, "minimum": True},
    ]

    assert average_days(lifespans) == 150


@pytest.mark.parametrize("lifespans", [[], [{"days": 206, "minimum": True}]])
def test_average_is_none_without_a_measured_lifespan(lifespans):
    assert average_days(lifespans) is None
