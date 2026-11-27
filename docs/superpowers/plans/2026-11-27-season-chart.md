# Battery Life by Season Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Not before late 2027.** Build once at least one measured set exists for each
season; until then the chart has nothing worth showing.

**Goal:** An **Average by season fitted** bar chart at the end of `battery-history`.

**Architecture:** A pure module, `core/battery_seasons.py`, groups past sets by the
meteorological season they were fitted in and draws eighth-block bars. A short
renderer in `commands/battery.py` lays it out with the existing section helpers
(`_echo_section`, `_cell`, `_age_colour`) and is called after **Average by make**.

**Tech Stack:** Python 3.13, Click, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-27-season-chart-design.md`

## Global Constraints

- British English in code, comments, output and documentation.
- Seasons: Spring Mar–May, Summer Jun–Aug, Autumn Sep–Nov, Winter Dec–Feb; always all four, in that order.
- Counted sets: `past_batteries` with `minimum: false` and a non-null `went_low`.
- Bars: at most 30 columns, eighth-blocks `▏▎▍▌▋▊▉█`, scaled to the longest season average.
- Widths measured on plain text, styled afterwards; no line over 100 characters.
- `commands/battery.py` must stay under 950 lines (865 now); `uvx ruff check .` and `uvx pyright` clean.
- Tests never touch the API or `stored_data/`.

## Review Focus

- A set fitted in December is Winter, and so is one fitted in January or February of the next year (the season spans a year end). Tested in Task 1.
- Every counted set in one season: that bar is the full 30 columns, the other three show `none yet`. Tested in Task 2.
- A very short average beside a long one still draws at least one eighth-block, never an empty bar beside a figure. Tested in Task 1.
- A hand-edited `fitted` that isn't a date: the set is left out and counted in the left-out line, not a crash. Tested in Task 1.
- Piped output (no colour) keeps the columns lined up. Tested in Task 2 (`CliRunner` output is plain).

---

### Task 1: Group sets by season and draw bars

**Files:**
- Create: `core/battery_seasons.py`
- Test: `tests/test_battery_seasons.py`

**Interfaces:**
- Consumes: `PastBattery` from `core/storage.py`.
- Produces:
  - `SEASONS: tuple[str, ...] = ("Spring", "Summer", "Autumn", "Winter")`
  - `season_of(fitted: str) -> str` — raises `ValueError` for a non-date.
  - `@dataclass(frozen=True) class SeasonSummary: season: str; days: tuple[int, ...]` with properties `average -> int | None` (rounded mean), `shortest -> int | None`, `longest -> int | None`.
  - `season_summaries(batteries: Sequence[PastBattery]) -> tuple[list[SeasonSummary], int]` — four summaries in `SEASONS` order, and how many sets were left out.
  - `bar(value: int, longest: int, width: int = 30) -> str`

- [ ] **Step 1: Write the failing tests**

```python
def test_season_of_follows_meteorological_seasons():
    assert season_of("2026-03-01") == "Spring"
    assert season_of("2026-08-31") == "Summer"
    assert season_of("2026-11-30") == "Autumn"
    assert season_of("2026-12-01") == "Winter"
    assert season_of("2027-02-28") == "Winter"

def test_summaries_list_all_four_seasons_in_order():
    summaries, left_out = season_summaries([])
    assert [s.season for s in summaries] == ["Spring", "Summer", "Autumn", "Winter"]
    assert all(s.average is None for s in summaries) and left_out == 0

def test_summaries_count_only_measured_sets():
    # measured Autumn 150 and 170; unknown-age (minimum) and never-warned sets left out
    summaries, left_out = season_summaries([measured("2027-10-01", 150),
        measured("2027-11-20", 170), unknown_age("2026-04-17", 209), never_warned("2027-06-01")])
    autumn = summaries[2]
    assert (autumn.average, autumn.shortest, autumn.longest, len(autumn.days)) == (160, 150, 170, 2)
    assert left_out == 2

def test_a_set_with_a_bad_fitted_date_is_left_out():
    summaries, left_out = season_summaries([measured("not-a-date", 100)])
    assert all(not s.days for s in summaries) and left_out == 1

def test_bar_is_full_width_for_the_longest():
    assert bar(230, 230) == "█" * 30

def test_bar_uses_eighth_blocks():
    assert bar(115, 230) == "█" * 15          # exactly half
    assert bar(117, 230) == "█" * 15 + "▎"    # 117/230*240 = 122.1 → 122 eighths

def test_bar_never_vanishes_for_a_short_average():
    assert bar(1, 1000) == "▏"
```

`measured`, `unknown_age` and `never_warned` are small helpers in the test file
building `PastBattery` dicts (`minimum` false/true, `went_low` set/None).

- [ ] **Step 2: Run to see them fail**

Run: `uv run python -m pytest tests/test_battery_seasons.py -q`
Expected: FAIL, `ModuleNotFoundError: core.battery_seasons`

- [ ] **Step 3: Implement `core/battery_seasons.py`**

Season from the month: `SEASONS[(month % 12) // 3 - 1]` puts Dec–Feb at index −1 (Winter).
`bar` rounds `value / longest * width * 8` to whole eighths, with a minimum of 1;
full blocks are `eighths // 8`, then `"▏▎▍▌▋▊▉"[rest - 1]` when `rest` isn't 0.

- [ ] **Step 4: Run to see them pass**

Run: `uv run python -m pytest tests/test_battery_seasons.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add core/battery_seasons.py tests/test_battery_seasons.py
git commit -m "Group battery lifespans by the season they were fitted"
```

### Task 2: Show the chart in battery-history

**Files:**
- Modify: `commands/battery.py` (`_print_lifespans`, plus a new `_print_season_averages` beside `_print_make_averages`)
- Modify: `CLAUDE.md` (the `battery-history` line under Battery Status)
- Test: `tests/test_battery.py`

**Interfaces:**
- Consumes: `SEASONS`, `season_summaries`, `bar` from Task 1; `_echo_section`, `_cell`, `_age_colour`, `_count` already in `commands/battery.py`.
- Produces: `_print_season_averages(all_batteries: list[PastBattery]) -> None`, called last in `_print_lifespans`.

Layout per row, all on plain text first: `  {season:<6}   {bar:<30}  {f"{avg}d ×{n}":>8}` and,
when the season has two or more sets, `  {shortest}–{longest}d` dim. An empty season shows
`none yet` dim in the figure column. Bar and figure take `_age_colour(average)`, bold figure.
Section title `Average by season fitted`, header `  Season   Average days to first low`.
Under the rows: a yellow `Fewer than 3 sets in a season: read it as a hint, not a result.`
when any season has 1 or 2 sets, and a dim
`{_count(left_out, 'set')} not counted: unknown age, or taken out before they warned.`
when `left_out` > 0. No section at all when no season has a set.

- [ ] **Step 1: Write the failing tests** (call `_print_season_averages` inside a `click.Context` or through `battery_history_command` with the history redirected, as the existing history tests do)

```python
def test_season_chart_is_left_out_with_no_measured_sets(capsys):
    _print_season_averages([unknown_age("2026-04-17", 209)])
    assert "Average by season fitted" not in capsys.readouterr().out

def test_season_chart_shows_every_season_and_lines_up():
    out = run_history_with([measured("2027-10-01", 150), measured("2027-11-20", 170),
                            measured("2027-07-01", 230)])
    lines = section_lines(out, "Average by season fitted")
    assert [l.split()[0] for l in lines[:4]] == ["Spring", "Summer", "Autumn", "Winter"]
    assert "█" * 30 in lines[1] and "230d ×1" in lines[1]
    assert "160d ×2" in lines[2] and "150–170d" in lines[2]
    assert "none yet" in lines[0] and "none yet" in lines[3]
    assert len({l.index("d ×") for l in lines[1:3]}) == 1   # figures line up
    assert "read it as a hint" in out
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run python -m pytest tests/test_battery.py -q -k season`
Expected: FAIL, `_print_season_averages` not defined

- [ ] **Step 3: Implement `_print_season_averages` and call it after `_print_make_averages`**

- [ ] **Step 4: Run the whole suite and the checks**

Run: `uv run python -m pytest -q && uvx ruff check . && uvx ruff format --check . && uvx pyright && wc -l commands/battery.py`
Expected: all pass, no findings, `commands/battery.py` under 950 lines

- [ ] **Step 5: Update CLAUDE.md** — add to the `battery-history` description: it ends with **Average by season fitted**, one bar per meteorological season of the fitting date, measured sets only (see the spec).

- [ ] **Step 6: Commit**

```bash
git add commands/battery.py tests/test_battery.py CLAUDE.md
git commit -m "Show battery life by season fitted in battery-history"
```
