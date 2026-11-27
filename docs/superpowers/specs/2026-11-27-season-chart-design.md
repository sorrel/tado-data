# Battery life by season: design

27 November 2026. To be built once a full year of measured sets exists
(probably late 2027). Nothing in it needs new data saved before then.

## Why

A valve works far harder in winter than in summer, so a set's lifespan
depends on when it was fitted. Every lifespan saved so far ran from April to
November, mostly through months with little heating. Without a seasonal
view, the winter sets fitted in November 2026 will look like a worse make or
a failing device, when it is only the season.

## What it shows

A new section at the end of `battery-history`, **Average by season fitted**:
one horizontal bar per season, showing the average days to first LOW of the
sets fitted in that season, and how many sets each bar is based on.

```
  Average by season fitted
  Season   Average days to first low
  ──────────────────────────────────────────────────────
  Spring   ████████████████████████████▌   212d ×3
  Summer   ██████████████████████████████  230d ×2
  Autumn   ███████████████████▏            148d ×4   120–171d
  Winter                                   none yet
  Fewer than 3 sets in a season: read it as a hint, not a result.
  5 sets not counted: unknown age, or taken out before they warned.
```

## Rules

- **Season** is the UK meteorological season of the set's `fitted` date:
  Spring Mar–May, Summer Jun–Aug, Autumn Sep–Nov, Winter Dec–Feb. Always
  listed in that order, all four, so the shape stays the same from year to
  year.
- **Counted:** `past_batteries` sets with `minimum: false` and a `went_low`,
  the same sets the other averages use (`_average_days`). Unknown-age sets,
  sets taken out before they warned, and batteries still fitted are left out.
  The number left out is given in a dim line.
- **Bar length** is scaled to the longest season average, at most 30 columns,
  drawn in eighth-blocks (`▏▎▍▌▋▊▉█`) so close averages still look different.
  The bar and the figure take `_age_colour`, as the other averages do.
- **Range** (shortest–longest, dim) is shown for a season with two or more
  sets.
- **Caveat:** if any season has from 1 to 2 sets, add a yellow line saying
  it is a hint, not a result.
- A season with no sets shows a dim `none yet`. If no season has a set, the
  whole section is left out, as **Average by make** is.
- Widths are measured on the plain text and styled afterwards (workspace
  rule). Piped output loses the colour through `click.echo`; the block
  characters stay.

## Approaches considered

1. **Terminal chart in `battery-history` (chosen).** Fits how the project
   already reports, needs no new dependency, and reads only
   `battery_history.json`, so it makes no requests.
2. **A browser page with a real chart.** Could look richer, but it would be
   the only thing in the project that isn't terminal output, and you'd need
   a browser to look at it. Not chosen.
3. **Hours of heating per set instead of season of fitting.** Fairer, since
   a set's seven months span several seasons, but it needs day reports back
   to every fitting date (about 19 requests a day fetched). Left for later;
   the season of fitting is simple and is what was asked for.

## Constraints

- `commands/battery.py` is at 865 lines out of the 950 allowed, so the season
  logic goes in a new pure module, `core/battery_seasons.py` (grouping, the
  averages, bar drawing), with only a short call from `battery-history`.
- Tests are pure: build `PastBattery` dicts and check the grouping, the
  scaling, the eighth-block rounding, and the empty and caveat cases.

## Left to the builder

The exact wording of the caveat and the left-out line, and the column width
of the header.
