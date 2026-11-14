# CLAUDE.md

## Project Overview

A Python CLI tool for reporting on Tado smart heating system status. Read-only — no control commands, just data and reporting. Started with battery level reporting.

**Main purpose:** Query the Tado API and present device/zone status in a clear terminal format.

## Critical Notes

- **Tado API rate limiting is extremely strict.** Never run tests or development commands that hit live API endpoints. Only test CLI structure and help output.
- **No third-party Tado libraries.** They're unmaintained. We use the Tado REST API v2 directly via `requests`.
- **Always use British English** in code, comments, output, and documentation.

## Running Commands

```bash
# Run the CLI
uv run python tado.py <command>

# Examples
uv run python tado.py auth        # Authenticate (opens browser)
uv run python tado.py battery     # Battery status report
uv run python tado.py battery-history  # Every replaced battery and the average lifespan
uv run python tado.py battery-replaced DEVICE [--make TEXT] [--old-make TEXT]  # Record that you replaced a device's batteries (serial or rough room name); asks the makes
uv run python tado.py battery-make DEVICE MAKE [--old-set]  # Record or correct the make of the fitted (or last removed) batteries
uv run python tado.py battery-reading DEVICE 30 40 [--date YYYY-MM-DD] [--note TEXT] [--old-set]  # Record a battery meter reading, one % per cell
uv run python tado.py status      # Home info and device counts
uv run python tado.py heat-check [--date YYYY-MM-DD]  # Rooms that warmed with no call for heat, and offline valves (default: yesterday)
```

`tools/completion.zsh`, sourced from `~/.zshrc`, adds a `tado` shell command with tab completion that works from any directory. It's bound to `tado` because football-stats already holds the completion for `uv`.

## Architecture

### Authentication

OAuth2 Device Code Grant flow (required by Tado since March 2025):
1. Request device code from `https://login.tado.com/oauth2/device_authorize`
2. User opens verification URL in browser to log in
3. Script polls for token
4. Access token (~10 min lifetime) and refresh token saved to `tokens.json`
5. Refresh token rotation — old token invalidated on each refresh, new one persisted
6. `tokens.json` is saved atomically, and each refresh holds `tokens.json.lock` (waiting up to 5 seconds), so a manual run and the scheduled heat check can't rotate the token at the same moment and lose the login
7. `get_access_token()` raises `LoginNeeded`, `AuthNetworkError` (Tado's login server unreachable or failing; the login may be fine) or `TokenLockBusy`. `connect(interactive=False)` never starts the browser login; it raises instead

**Public client ID:** `1bb50063-6b0c-4d11-bd99-387f4a91cc46`

### API

- **Base URL:** `https://my.tado.com/api/v2`
- **Key endpoints:**
  - `GET /me` — account info including `homeId`
  - `GET /homes/{homeId}/devices` — all devices (includes `batteryState`)
  - `GET /homes/{homeId}/zones` — zones/rooms with device assignments
  - `GET /homes/{homeId}/zones/{zoneId}/state` — zone state (temperature, humidity, etc.)

### Battery Status

- Simple string field: `"NORMAL"` or `"LOW"` (no percentage available)
- Present on battery-powered devices only (thermostats, radiator valves)
- Absent on mains-powered devices (gateway, boiler unit)
- `battery-replaced`, `battery-reading` and `battery-make` take a serial or a rough room name (`loo`, `kitchn`). A serial makes no request to Tado; a room name fetches the zone list. Matching ignores case, spaces and punctuation and tries exact, then contains, then close spelling; a close-spelling match asks for confirmation. A room with two battery devices, or a name matching two rooms, stops and asks for the serial. The mains-wired hall thermostat is never chosen
- `battery-replaced` is the only thing that marks a battery as replaced. Its lifespan (fitting to first low warning) is then kept permanently in that device's `past_batteries` in `stored_data/battery_history.json`. A set taken out before it ever warned is kept too, with `went_low: null` and its time in saved as a minimum (shown as `never` and `≥209d`); it is left out of both averages. Running `battery-replaced` a second time on the same day changes nothing
- `battery` shows each device's **Average**: the mean of its measured lifespans and how many sets, e.g. `205d ×2`. Unknown-age (`≥`) sets and sets taken out before they warned are left out, so it stays blank until a device has a measured set. `battery-history` lists the same figure under **Average by device**, after the overall average
- Tracking began on 2026-04-17, so batteries dated then are of unknown age: their lifespans are saved with `minimum: true` and shown as, for example, `≥206d`
- `stored_data/` is local only and cannot be rebuilt from Tado, so saves are atomic and each one keeps the previous version as `battery_history.json.bak`. A damaged file stops the command with an error; it must never be treated as empty, or the next save would overwrite the real history
- `battery-reading` keeps what a battery meter said, one percentage per cell, in `meter_readings` (`date`, `percent`, optional `note`). Like `low_periods`, it belongs to the batteries now fitted: every save must carry it across, and `battery-replaced` moves it into that battery's record in `past_batteries`. `--old-set` puts a reading on the set most recently taken out instead (dated the day they came out unless `--date` is given), for a reading not recorded before `battery-replaced`. `battery-history` lists every reading
- Every cell is AA, so only the **make** is recorded (`make`, optional). `battery-replaced` asks for the make of the new set and, only if it wasn't recorded, of the set taken out; Enter skips either, and `--make` / `--old-make` answer without asking. The fitted set's `make` moves into its `past_batteries` record on replacement, and like `meter_readings` every save must carry it across. A make typed in a different case from one already recorded takes the recorded spelling, so one make isn't counted twice. `battery-make` records or corrects one afterwards (`--old-set` for the set last taken out). `battery-history` shows each set's make and an **Average by make**. Makes began on 14 November 2026; earlier sets have none
- A LOW device that goes offline is taken to have died: the first date seen is kept as `died`, and cleared if the device comes back online. `battery-history` shows days on low, as a minimum if the battery was replaced before dying

### Known Issue: Tado's LOW Warning Is Not the End of the Battery

On 9 November 2026, valve `VA0149052928` reported `LOW` after 204 days. Its two non-rechargeable batteries were taken out, both measured 90% on a charge meter, and they were put back in. Batteries reading 10% have also been seen to work well, so the meter's percentage does not reliably match what the valve reacts to.

On 11 November 2026, the hall valve `VA2062453504` reported `LOW` with batteries measuring 30% and 40%; they were left in. Both readings are recorded with `battery-reading`. Both cases point to the same thing: Tado warns early, leaving a long window to change the batteries.

The likeliest explanation (not confirmed) is voltage under load. A charge meter applies a light load, but the valve probably measures while its motor is running, when a part-used alkaline cell sags much further. Two things make that sag worse: dirty or loose contacts (taking the batteries out and refitting them wipes the contacts, which may be why `VA0149052928` went back to `NORMAL`) and cold weather.

What follows from this:

- A saved lifespan is the time to the **first low warning**, not the total life of the batteries. `On low` in `battery-history` is what shows how much further they went.
- `LOW` going back to `NORMAL` is **not** evidence of a replacement, because the same batteries may have gone back in. The code must never infer a replacement; only `battery-replaced` records one.
- Do not run `battery` while batteries are out of a low device: it will look offline and be recorded as having died.
- The same valve went back to `NORMAL` once the batteries were refitted, so each spell of `LOW` is kept in `low_periods` (`from`, `to`; `to` is null while still low; `seen` is the last day `battery` saw it LOW, absent on spells saved before 14 November 2026, which fall back to `from`). `low_since` stays as the first warning. `battery` shows **First low** (the first day ever seen low), **Latest low** (the latest spell's `seen`, so the most recent day seen low) and how many spells (for the batteries now fitted, in red only while still low). `battery-history` lists every spell with when it went low, its last day seen low and when it was normal again, so the start of a later spell is still visible there. `seen` moves only when `battery` runs, not with the heat check.

### Known Issue: Battery Status Says Nothing About Whether the Valve Works

In November 2026 the mechanical adaptor between the downstairs loo valve and its radiator was failing. The valve's motor ran as normal but could not close the radiator, so the radiator stayed hot whatever Tado asked for. Tado raised no warning, and the battery stayed `NORMAL`. Once the adaptor was put right, the radiator went cold when it should. The sign of this fault is in the data rather than the device status: a room that keeps warming while Tado asks that zone for no heat. `heat-check` (below) now looks for it every morning.

### Heat Check

`heat-check` reads each heating zone's day report
(`GET /homes/{homeId}/zones/{zoneId}/dayReport?date=YYYY-MM-DD`, about every
15 minutes) and reports two kinds of fault (design:
`docs/superpowers/specs/2026-11-11-heat-check-design.md`):

- **Warming:** the room rose 2.0° or more during a spell with no call for heat,
  ignoring the first 30 minutes after a call ends. This is a valve that can't
  close, as the Downstairs Loo's couldn't in November 2026. Being above the set
  point isn't enough on its own; sun or a warm neighbour can do that.
- **Offline:** the zone's measuring device was out of contact for an hour or
  more in total during the day.

Days are UK local days (`Europe/London`). Fetched reports are kept in
`stored_data/day_reports/<date>/<zoneId>.json`, so no day is fetched twice;
today's report is never fetched or saved.

`heat-check --scheduled` runs from launchd at 07:00, and again at 10:00,
13:00, 16:00, 19:00 and 22:00 so a Mac switched on late still gets checked;
once a day is checked, later runs make no requests (install with
`tools/install-heat-check.sh`, which sends a test notification; log in
`~/Library/Logs/tado-heat-check.log`). It deliberately doesn't run at login,
when the network may not be up yet.
It checks every day since the last check, up to 7 days back, and records
progress and known faults in `stored_data/heat_check.json`. It notifies on
this Mac only for a new fault, a known one again once a week, a cleared one,
or the check failing (expired login, network, Tado error, damaged file,
unexpected error, or Tado listing no heating zones). Anything that fails
inside the check notifies; the one silent case is the job never starting at
all (Mac off all day, or `uv` moved), and the log shows when it last ran.
Notifications may need allowing under Script Editor in System Settings →
Notifications. The account has Auto-Assist, so about 20,000 requests a day;
a checked day costs about 19.

### Zone Control & Heating Circuits

- `GET /homes/{homeId}/zones` — zone list with devices and their `duties` arrays
- `GET /homes/{homeId}/zones/{zoneId}/control` — zone control config; the key field is `heatingCircuit`
- `heatingCircuit: <number>` → zone is connected to a heating circuit and fires the boiler when calling for heat
- `heatingCircuit: null` → zone has no circuit assigned; the valve opens but cannot fire the boiler independently
- Zone type `HOT_WATER` is excluded from the zones command (heating zones only)

### Device Types

| Type | Description |
|------|-------------|
| `RU01`/`RU02` | Smart thermostat / room sensor |
| `VA01` | Radiator valve |
| `BU01` | Boiler unit (mains) |
| `GW02`/`GW03` | Gateway (mains) |

## File Structure

- `tado.py` — CLI entry point (Click)
- `core/auth.py` — OAuth2 device code flow and token management
- `core/client.py` — TadoClient class for API requests
- `commands/setup.py` — auth, logout, status commands + ColouredGroup
- `commands/battery.py` — Battery reporting command
- `commands/heat_check.py` — heat-check command and its scheduled run
- `core/heat_detect.py` — finds warming and offline faults in a day report (pure)
- `core/heat_alerts.py` — decides which faults to notify: new, weekly, cleared (pure)
- `core/heat_store.py` — saved day reports and heat-check state in `stored_data/`
- `core/notify.py` — macOS notifications through `osascript`
- `tools/heat-check.plist.template`, `tools/install-heat-check.sh` — the 07:00 launchd schedule
- `tests/fixtures/dayreport_fault.json` — the real 10 November 2026 loo report, weather removed
- `tokens.json` — Saved auth tokens (gitignored)
- `tests/` — pytest suite (pure logic only; never hits the API)

## Code Style

- No line over 100 characters (`[tool.ruff]` in `pyproject.toml`): `uvx ruff format .`
  wraps code, and `uvx ruff check --select E501 .` finds long strings it can't.
- Files up to 950 lines; functions short enough to read at a glance (about 40
  lines). Split a long function into named steps rather than adding comments
  to navigate it.
- `uvx ruff check .` and `uvx pyright` must both be clean. Pyright checks the
  application code only (`[tool.pyright]` in `pyproject.toml`), not the tests.
- The shape of `battery_history.json` is set out as `TypedDict`s at the top of
  `core/storage.py` (`DeviceHistory`, `PastBattery`, `MeterReading`, …). Keep
  them in step with any change to what is saved.
- A heat-check finding is a `Warming` or an `Offline` (`core/heat_detect.py`),
  each with only the fields it has; `format_finding` matches on the type.

## Testing

```bash
uv run python -m pytest -q
```

`pytest` is declared in `[dependency-groups]`, which `uv sync` installs by
default — no `--extra dev` needed.

Every test is pure logic or a stub: `date.today()` is pinned via a `date`
subclass in `tests/conftest.py` so date-dependent assertions don't rot, and
the battery history file is redirected to `tmp_path` so `stored_data/` is
never written during a test run. Keep it that way — the rate-limit rule above
means no test may ever reach a live endpoint.

## Dependencies

- `click>=8.0.0` — CLI framework
- `requests>=2.28.0` — HTTP client

## Git Workflow

**"Release" means the whole process: commit → push → PR → merge.** When Duncan
says "release it" (or "release the update"), do all four steps, not just the
commit.

**Always go through a pull request. Never commit directly to `main`.**

Even though this is a single-person project, every change goes on a feature
branch and is merged via PR:

```bash
git checkout -b feature/descriptive-name
# commit your work on the branch
git push -u origin feature/descriptive-name
gh pr create
```

This keeps `main` clean, gives CodeQL a chance to run before merge, and leaves a
reviewable record of each change.

## Design Decisions

- Modelled after the hue-control project (same directory, similar CLI patterns)
- Click CLI with `ColouredGroup` for coloured help output
- Token persistence in project-local `tokens.json` (gitignored)
- Automatic token refresh on every request (access tokens are short-lived)
