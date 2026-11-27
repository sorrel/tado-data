"""Tests for grouping battery lifespans by the season they were fitted, and drawing bars."""

from core.battery_seasons import bar, season_of, season_summaries


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
