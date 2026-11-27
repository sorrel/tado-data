"""Tests for grouping battery lifespans by the season they were fitted, and drawing bars."""

import xml.etree.ElementTree as ET

import pytest

from tado_data.core.battery_seasons import (
    AGE_HEX,
    age_band,
    bar,
    season_of,
    season_summaries,
    season_svg,
)

SVG = "{http://www.w3.org/2000/svg}"


def measured(fitted, days):
    return {
        "fitted": fitted,
        "went_low": "2028-01-01",
        "replaced": "2028-01-02",
        "days": days,
        "minimum": False,
    }


def unknown_age(fitted, days):
    return {**measured(fitted, days), "minimum": True}


def never_warned(fitted):
    return {**measured(fitted, 100), "went_low": None, "minimum": True}


# --- season_of --------------------------------------------------------------


def test_season_of_follows_meteorological_seasons():
    assert season_of("2026-03-01") == "Spring"
    assert season_of("2026-05-31") == "Spring"
    assert season_of("2026-06-01") == "Summer"
    assert season_of("2026-08-31") == "Summer"
    assert season_of("2026-09-01") == "Autumn"
    assert season_of("2026-11-30") == "Autumn"
    assert season_of("2026-12-01") == "Winter"
    assert season_of("2027-01-15") == "Winter"
    assert season_of("2027-02-28") == "Winter"


# --- season_summaries -------------------------------------------------------


def test_summaries_list_all_four_seasons_in_order():
    summaries, left_out = season_summaries([])
    assert [s.season for s in summaries] == ["Spring", "Summer", "Autumn", "Winter"]
    assert all(s.average is None for s in summaries)
    assert left_out == 0


def test_summaries_count_only_measured_sets():
    summaries, left_out = season_summaries(
        [
            measured("2027-10-01", 150),
            measured("2027-11-20", 170),
            unknown_age("2026-04-17", 209),
            never_warned("2027-06-01"),
        ]
    )
    autumn = summaries[2]
    assert (autumn.average, autumn.shortest, autumn.longest) == (160, 150, 170)
    assert len(autumn.days) == 2
    assert all(not s.days for s in (summaries[0], summaries[1], summaries[3]))
    assert left_out == 2


def test_a_measured_set_with_no_went_low_is_left_out():
    summaries, left_out = season_summaries([{**measured("2027-10-01", 150), "went_low": None}])
    assert all(not s.days for s in summaries)
    assert left_out == 1


def test_a_set_with_a_bad_fitted_date_is_left_out():
    summaries, left_out = season_summaries([measured("not-a-date", 100)])
    assert all(not s.days for s in summaries)
    assert left_out == 1


def test_an_empty_season_has_no_range():
    summaries, _ = season_summaries([])
    assert summaries[0].shortest is None and summaries[0].longest is None


# --- bar --------------------------------------------------------------------


def test_bar_is_full_width_for_the_longest():
    assert bar(230, 230) == "█" * 30


def test_bar_uses_eighth_blocks():
    assert bar(115, 230) == "█" * 15  # exactly half
    assert bar(117, 230) == "█" * 15 + "▎"  # 117/230*240 = 122.1 → 122 eighths


def test_bar_never_vanishes_for_a_short_average():
    assert bar(1, 1000) == "▏"


def test_bar_follows_the_width_given():
    assert bar(10, 10, width=8) == "█" * 8


# --- age_band ---------------------------------------------------------------


def test_age_band_changes_every_hundred_days():
    assert [age_band(d) for d in (0, 99, 100, 250, 400, 900)] == [0, 0, 1, 2, 4, 4]


# --- season_svg -------------------------------------------------------------


def _bars(svg):
    root = ET.fromstring(svg)
    return [r for r in root.iter(f"{SVG}rect") if r.get("class") == "bar"]


def test_svg_is_well_formed_with_a_bar_per_measured_season():
    summaries, left_out = season_summaries(
        [measured("2027-10-01", 150), measured("2027-11-20", 170), measured("2027-07-01", 230)]
    )
    bars = _bars(season_svg(summaries, left_out))
    assert len(bars) == 2
    widths = sorted(float(b.get("width")) for b in bars)
    assert widths[0] / widths[1] == pytest.approx(160 / 230, rel=0.01)
    assert {b.get("fill") for b in bars} == {AGE_HEX[1], AGE_HEX[2]}


def test_svg_lists_every_season_and_the_figures():
    svg = season_svg(*season_summaries([measured("2027-10-01", 150), measured("2027-11-20", 170)]))
    for text in ("Spring", "Summer", "Autumn", "Winter", "160d ×2", "150–170d", "none yet"):
        assert text in svg
    assert "read it as a hint" in svg


def test_svg_says_what_it_left_out():
    svg = season_svg(
        *season_summaries([measured("2027-10-01", 150), unknown_age("2026-04-17", 209)])
    )
    assert "1 set not counted" in svg


def test_svg_has_a_viewbox_so_it_scales():
    svg = season_svg(*season_summaries([measured("2027-10-01", 150)]))
    assert ET.fromstring(svg).get("viewBox", "").startswith("0 0 ")
