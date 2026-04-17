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
uv run python tado.py status      # Home info and device counts
```

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

## Dependencies

- `click>=8.0.0` — CLI framework
- `requests>=2.28.0` — HTTP client

## Git Workflow

Single-person project — commit directly to `main`. No feature branches needed.

## Design Decisions

- Modelled after the hue-control project (same directory, similar CLI patterns)
- Click CLI with `ColouredGroup` for coloured help output
- Token persistence in project-local `tokens.json` (gitignored)
- Automatic token refresh on every request (access tokens are short-lived)
