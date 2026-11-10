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
uv run python tado.py battery-replaced SERIAL  # Record that you replaced a device's batteries
uv run python tado.py status      # Home info and device counts
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
- `battery-replaced SERIAL` is the only thing that marks a battery as replaced. Its lifespan (fitting to first low warning) is then kept permanently in that device's `past_batteries` in `stored_data/battery_history.json`
- Tracking began on 2026-04-17, so batteries dated then are of unknown age: their lifespans are saved with `minimum: true` and shown as, for example, `≥206d`
- `stored_data/` is local only and cannot be rebuilt from Tado, so saves are atomic and each one keeps the previous version as `battery_history.json.bak`. A damaged file stops the command with an error; it must never be treated as empty, or the next save would overwrite the real history
- A LOW device that goes offline is taken to have died: the first date seen is kept as `died`, and cleared if the device comes back online. `battery-history` shows days on low, as a minimum if the battery was replaced before dying

### Known Issue: Tado's LOW Warning Is Not the End of the Battery

On 9 November 2026, valve `VA0149052928` reported `LOW` after 204 days. Its two non-rechargeable batteries were taken out, both measured 90% on a charge meter, and they were put back in. Batteries reading 10% have also been seen to work well, so the meter's percentage does not reliably match what the valve reacts to.

What follows from this:

- A saved lifespan is the time to the **first low warning**, not the total life of the batteries. `On low` in `battery-history` is what shows how much further they went.
- `LOW` going back to `NORMAL` is **not** evidence of a replacement, because the same batteries may have gone back in. The code must never infer a replacement; only `battery-replaced` records one.
- Do not run `battery` while batteries are out of a low device: it will look offline and be recorded as having died.
- The same valve went back to `NORMAL` once the batteries were refitted, so each spell of `LOW` is kept in `low_periods` (`from`, `to`; `to` is null while still low). `low_since` stays as the first warning. `battery` shows the first, the latest and how many (for the batteries now fitted, in red only while still low), and `battery-history` lists them all.

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
- `tokens.json` — Saved auth tokens (gitignored)
- `tests/` — pytest suite (pure logic only; never hits the API)

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
