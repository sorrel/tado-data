# Heat check: catch valves that heat a room Tado has turned down

Design, 11 November 2026.

## Why

In November 2026 the mechanical adaptor between the Downstairs Loo valve and
its radiator failed. The valve motor ran normally but couldn't close the
radiator, so the radiator stayed hot whenever the boiler fired for any other
room. Tado gave no warning and the battery stayed `NORMAL`. Nobody knew until
the room was noticed to be warm.

The fault shows clearly in Tado's own data. On 10 November the loo asked for
heat once (05:20–05:34), yet the room climbed to 21.5° by 06:45 against a set
point of 17.5°, and reached 25.1° at 17:45 with heating off. Room temperature
rising with no call for heat is the signature.

Duncan wants this caught automatically, and to be told only when there's a
problem.

## Goals

- Every morning, check the previous day for every heating zone and raise a
  macOS notification if any zone warmed up while Tado wasn't asking for heat,
  or if a zone's measuring device was offline.
- Stay silent on a normal day, and don't repeat a known fault more than
  once a week (see Repeat notifications).
- Never be silent when the check itself can't run (see Anti-goals).
- Let the same check run by hand for any day: `tado heat-check [--date YYYY-MM-DD]`.

## Non-goals

- No control of the heating. The project stays read-only.
- No hourly polling. The day report already holds the whole day at about
  15-minute resolution, so once a day is enough.
- No email, phone or other notification channel. Just this Mac.
- No telling which of two valves in one zone is at fault (the Lounge has two);
  the zone is flagged, and that's all.

## Anti-goals (failure even if it "works")

- **A broken job that looks like a healthy house.** If authentication has
  expired, the network is down, Tado errors, or the code crashes, a
  notification must say the check didn't run and why. No news must always mean
  good news.
- **Hanging unattended.** The scheduled run must never start the device-code
  login (it waits up to ten minutes for a browser that nobody's at). It must
  fail fast and notify "run `tado auth`".
- **Losing the login.** Tado rotates the refresh token on every refresh. A
  half-written `tokens.json`, or a manual run and the scheduled run refreshing
  at the same moment, can leave no valid token and force a re-login.
- **Burning the API allowance.** Never fetch a day report already saved.
- **Crying wolf.** False alarms on ordinary warm days will get the
  notification ignored. Prefer missing a marginal case to alerting on noise.

## Constraints

- Tado's rate limits are strict. Tests must never reach a live endpoint
  (CLAUDE.md); all detection logic is tested against saved reports.
- British English everywhere, including notification text.
- `stored_data/` is local, gitignored and cannot be rebuilt beyond Tado's own
  retention, so writes are atomic like `battery_history.json`.
- macOS only (launchd, macOS notifications).
- There is no 1Password `.env` in this project; the only secret is
  `tokens.json`.

## The data (from a real response)

`GET /homes/{homeId}/zones/{zoneId}/dayReport?date=YYYY-MM-DD`, one call per
zone per day.

**Fixtures (settled).** Duncan ran a one-off read-only fetch on 11 November,
saved outside the repo at
`/private/tmp/claude-501/-Users-duncan-Developer-Program-scripts-tado-data/874106e1-de02-4999-8e33-3c0d2b03f6f9/scratchpad/loo_dayreport_2026-11-10.json`
(and `…2026-11-11.json`). The 10 November report is the real fault day and
also contains the valve going offline at 19:35, so it covers both findings.
It is committed as `tests/fixtures/dayreport_fault.json` with the `weather`
block removed: the repo is public, and the report holds no names, IDs or
location, but outside temperature by time is best left out. The
11 November report was fetched mid-day, so it is **not** used; "offline all
day" is tested with a small hand-made report instead.

Fields used:

- `measuredData.insideTemperature.dataPoints[]`: `timestamp`,
  `value.celsius`, about every 15 minutes.
- `callForHeat.dataIntervals[]`: `from`, `to`, `value` of `NONE`, `LOW`,
  `MEDIUM` or `HIGH`.
- `settings.dataIntervals[]`: `value.power` (`ON`/`OFF`) and
  `value.temperature.celsius` when on.
- `measuredData.measuringDeviceConnected.dataIntervals[]`: `value` boolean.

Intervals run from 23:45 the day before to 00:15 the day after, in UTC.

## How detection works (decided)

A **no-heat spell** is a continuous stretch where `callForHeat` is `NONE`.
Within each spell, a zone is flagged if the room temperature **rises by 2.0°
or more**: from its lowest point in the spell to a later higher point. "Above
the set point" alone is not enough, since sun, cooking or a warm neighbouring
room can do that; the rise is what shows heat arriving.

Heat already in the radiator carries on for a while after a call ends, so the
first 30 minutes of each spell are ignored when looking for the rise. *(My
call: the builder should check 30 minutes against the fixtures and adjust if
the fault day needs a shorter window to be caught, recording what was chosen
and why.)*

A zone is also reported if `measuringDeviceConnected` is false for an hour or
more in total during the day; the report gives the time it went offline.
Shorter drops (a battery swap, a brief radio dropout) are ignored. *(My call,
proposed to Duncan, not objected to.)*

## Repeat notifications (decided by Duncan)

Not every morning, but once a week, even for a fault he already knows about:

- A fault is **new** when a zone has a finding of a kind (warming, offline)
  that it didn't have on the previous checked day. A new fault is notified
  that morning.
- While it carries on, it is notified again **once a week** (7 days after it
  was last notified), so a known fault isn't forgotten.
- Findings are still printed and logged every day; only the notification is
  held back.
- When a fault has been absent for a checked day, it counts as cleared, and
  one "cleared" notification is sent (for example "Downstairs Loo is back
  online"). *(My call: it confirms a repair took, as with the loo valve
  being refitted.)*

This needs a small record in `stored_data/` per zone and kind: first seen,
last seen, last notified. Saved atomically like the battery history.

## API budget (decided: Auto-Assist)

Duncan pays for Auto-Assist, so the account's limit is about 20,000 requests a
day, shared with manual `battery`, `zones` and `status` runs. One checked day
costs about 19 requests (one day report per heating zone plus `/me` and the
zones list; refreshing the token goes to the login server), so even a full
seven-day catch-up (about 130) is far inside it. No per-run cap is needed.

- A rate-limit response (HTTP 429) still stops the run at once, keeps
  everything already saved, and is reported in its own notification ("Tado's
  daily request limit was reached; the check will carry on tomorrow").
- If Tado's responses include rate-limit headers, the remaining allowance is
  logged with each run.

## What is reported

Command output (`tado heat-check`), one line per finding, for example:

```
  Downstairs Loo  warmed 6.6° (18.6° → 25.2°) between 10:00 and 18:00 with no call for heat
  Downstairs Loo  offline from 19:35
```

with times shown in UK local time. A clean day prints a single "No problems on
<date>" line.

The notification gathers the findings: a title such as "Tado heat check" and a
body naming the rooms, for example "Downstairs Loo warmed 6.6° with the
heating off". Failures get their own wording, for example "Heat check didn't
run: Tado login has expired. Run tado auth."

## Saving day reports

Each fetched report is saved under `stored_data/day_reports/<YYYY-MM-DD>/<zoneId>.json`,
written atomically. Running the check for a day that's already saved makes no
API calls for those zones. The current day is never saved (it's incomplete);
the check refuses today and future dates.

## Scheduling (decided)

A launchd agent in `~/Library/LaunchAgents` runs `tado heat-check --scheduled`
at 07:00 each day. launchd runs a missed calendar job when the Mac wakes, so a
sleeping Mac doesn't lose the day. The plist lives in the repo (under `tools/`)
with an install step documented, like `tools/completion.zsh`. Output and errors
go to a log file in `stored_data/` or `~/Library/Logs`, so a notification can
be followed up.

`--scheduled` means: never start the interactive login, notify on every
problem and every failure, print nothing a person needs to see.

If 07:00's run is missed (the Mac was off), every unchecked day up to seven
days back is caught up in that run, oldest first; older days are skipped and
logged as not checked. The
last checked date is kept in `stored_data/` so days aren't checked twice.

## Login safety (decided)

- `save_tokens` becomes atomic (write to a temporary file, `fsync`, rename,
  0600 permissions), as `_save_json` already does.
- A refresh takes an exclusive file lock beside `tokens.json` so a manual and
  a scheduled run can't rotate the token at the same time.
- A network failure during refresh is reported as a network failure, not as
  "login needed".
- `TadoClient.connect` gains a way to refuse the device-code flow (for
  example `connect(interactive=False)`); the scheduled run uses it.

## Settled during review (my calls)

- A failed run does not move the last-checked date on, so the next run
  retries the day.
- The token lock waits briefly (a few seconds) for the other run, then gives
  up with a reported failure rather than refreshing unguarded.
- Day boundaries are UK local days (Europe/London, so British Summer Time is
  handled); the report's UTC timestamps are converted for display.
- The launchd plist in the repo is a template with no personal paths; the
  install step fills them in.

## Left to the builder

- The notification mechanism (`osascript -e 'display notification …'` or
  similar), as long as it works from a launchd agent on macOS 26 and needs no
  third-party install. If it needs a one-time permission, document it.
- Module layout: a `commands/heat_check.py` command and a pure detection
  module that takes a parsed day report and returns findings, so it can be
  tested on the fixtures.
- Exact wording of output and notifications, within the examples above.
- How zone names are got (the zones call adds one request a day; acceptable).

## Testing

Pure logic only, never the live API: detection against the two real fixtures
plus small hand-made reports for the edges (warm room with no rise, rise
inside the 30-minute carry-over, a call for heat in the middle of a spell,
partial offline, no data points). Saving and skipping already-saved days,
missed-day catch-up, refusing today, refusing interactive login when
scheduled, atomic token saves and the lock. The notifier is stubbed in tests.
