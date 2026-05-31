"""
OAuth2 Device Code Grant flow for Tado API authentication.

Uses the device code flow as required by Tado since March 2025.
Tokens are persisted to tokens.json and refreshed automatically.
"""

import json
import time
from pathlib import Path

import click
import requests

# Tado's public OAuth2 client ID
CLIENT_ID = "1bb50063-6b0c-4d11-bd99-387f4a91cc46"

# OAuth2 endpoints
DEVICE_AUTH_URL = "https://login.tado.com/oauth2/device_authorize"
TOKEN_URL = "https://login.tado.com/oauth2/token"

# Token storage path (project-local)
TOKEN_FILE = Path(__file__).parent.parent / "tokens.json"


def load_tokens() -> dict | None:
    """Load saved tokens from disk."""
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_tokens(tokens: dict) -> None:
    """Persist tokens to disk with owner-only permissions."""
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    TOKEN_FILE.chmod(0o600)


def clear_tokens() -> None:
    """Remove saved tokens."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


def device_code_flow() -> dict | None:
    """
    Run the OAuth2 Device Code Grant flow.

    Returns token dict on success, None on failure.
    """
    # Step 1: Request device code
    click.echo("Requesting device authorisation...")
    try:
        resp = requests.post(DEVICE_AUTH_URL, data={
            "client_id": CLIENT_ID,
            "scope": "offline_access",
        }, timeout=10)
    except requests.RequestException as e:
        click.echo(f"Network error starting device auth: {e}", err=True)
        return None

    if resp.status_code != 200:
        click.echo(f"Failed to start device auth: {resp.status_code} {resp.text}", err=True)
        return None

    auth_data = resp.json()
    verification_url = auth_data.get("verification_uri_complete")
    device_code = auth_data.get("device_code")
    interval = auth_data.get("interval", 5)
    expires_in = auth_data.get("expires_in", 600)

    # Step 2: Ask user to authenticate
    click.echo()
    click.echo(click.style("Please open this URL in your browser to log in:", fg="yellow"))
    click.echo(click.style(f"  {verification_url}", fg="bright_white", bold=True))
    click.echo()
    click.echo(f"Waiting for authorisation (expires in {expires_in // 60} minutes)...")

    # Step 3: Poll for token
    deadline = time.time() + expires_in

    while time.time() < deadline:
        time.sleep(interval)

        try:
            resp = requests.post(TOKEN_URL, data={
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }, timeout=10)
        except requests.RequestException:
            continue

        if resp.status_code == 200:
            tokens = resp.json()
            save_tokens(tokens)
            click.echo(click.style("Authorisation successful!", fg="green"))
            return tokens

        error = resp.json().get("error", "")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 1
            continue
        else:
            click.echo(f"Authorisation failed: {error}", err=True)
            return None

    click.echo("Authorisation timed out.", err=True)
    return None


def refresh_access_token(refresh_token: str) -> dict | None:
    """
    Refresh the access token using a refresh token.

    Tado uses refresh token rotation, so the new refresh token
    must be persisted (the old one is invalidated).
    """
    try:
        resp = requests.post(TOKEN_URL, data={
            "client_id": CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }, timeout=10)
    except requests.RequestException:
        return None

    if resp.status_code == 200:
        tokens = resp.json()
        save_tokens(tokens)
        return tokens

    return None


def get_access_token() -> str | None:
    """
    Get a valid access token, refreshing if necessary.

    Returns the access token string, or None if auth is needed.
    """
    tokens = load_tokens()
    if not tokens:
        return None

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return None

    # Always refresh — access tokens are short-lived (~10 min)
    # and we don't store the expiry time
    refreshed = refresh_access_token(refresh_token)
    if refreshed:
        return refreshed.get("access_token")

    return None
