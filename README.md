# tado-data

A read-only Python CLI tool for reporting on Tado smart heating system status.

## Features

- Battery status report for all devices
- Zone controller map — which heating zones fire the boiler vs operate passively
- Home info and device counts
- OAuth2 authentication with automatic token refresh

## Usage

```bash
uv run python tado.py auth        # Authenticate (opens browser)
uv run python tado.py battery     # Battery status report
uv run python tado.py zones       # Which zones fire the boiler vs operate passively
uv run python tado.py status      # Home info and device counts
```

## Battery History

Each time `battery` runs, it records when each device entered its current state (NORMAL or LOW). This is persisted locally in `stored_data/battery_history.json`. The **Good since** and **Low since** columns show how long a device has been in its current state — useful for spotting batteries that have been low for a while. If a device is seen for the first time, today's date is used as the baseline.

## Authentication

Uses OAuth2 Device Code Grant flow. Run `auth` to open a browser login page — tokens are saved locally to `tokens.json` and refreshed automatically.

## Dependencies

- Python 3.12+
- `click` — CLI framework
- `requests` — HTTP client

Install dependencies with `uv sync`.
