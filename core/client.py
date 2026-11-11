"""
Tado API client.

Handles authenticated requests to the Tado REST API v2.
"""

from datetime import date

import click
import requests

from core.auth import AuthError, LoginNeeded, device_code_flow, get_access_token

API_BASE = "https://my.tado.com/api/v2"


class TadoAPIError(Exception):
    """A strict request failed. status is the HTTP status, or None if Tado wasn't reached."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class RateLimited(TadoAPIError):
    """Tado's daily request limit was reached (HTTP 429)."""


class TadoClient:
    """Client for the Tado REST API v2."""

    def __init__(self):
        self.session = requests.Session()
        self.home_id = None
        # Tado's rate-limit headers from the latest response, for logging
        self.rate_limit: str | None = None

    def connect(self, interactive: bool = True) -> bool:
        """
        Authenticate and fetch the home ID.

        Returns True if connection is successful. Interactively, a missing or
        expired login starts the browser login. With interactive=False nothing
        ever prompts: login problems are raised as AuthError for the caller to
        report.
        """
        try:
            token = get_access_token()
        except LoginNeeded:
            if not interactive:
                raise
            click.echo("No valid token found. Starting authorisation flow...")
            tokens = device_code_flow()
            if not tokens:
                return False
            token = tokens.get("access_token")
        except AuthError as error:
            if not interactive:
                raise
            click.echo(f"Couldn't log in to Tado: {error}.", err=True)
            return False

        self.session.headers.update({
            "Authorization": f"Bearer {token}",
        })

        # Fetch home ID
        me = self._request("GET", "/me", strict=not interactive)
        if not me:
            click.echo("Failed to fetch account info. Try re-authenticating.", err=True)
            return False

        # homeId can be top-level or nested under homes
        self.home_id = me.get("homeId")
        if not self.home_id:
            homes = me.get("homes", [])
            if homes:
                self.home_id = homes[0].get("id")

        if not self.home_id:
            click.echo("Could not determine home ID from account.", err=True)
            return False

        return True

    def _request(self, method: str, path: str, strict: bool = False) -> dict | list | None:
        """
        Make an authenticated API request.

        Returns parsed JSON response, or None on failure. With strict=True a
        failure raises TadoAPIError (RateLimited for HTTP 429) instead, so an
        unattended caller can say exactly what went wrong.
        """
        url = f"{API_BASE}{path}"
        try:
            resp = self.session.request(method, url, timeout=10)
        except requests.RequestException as e:
            if strict:
                raise TadoAPIError(f"couldn't reach Tado ({e})") from e
            click.echo(f"Request failed: {e}", err=True)
            return None

        limits = [f"{name}={value}" for name, value in resp.headers.items() if "ratelimit" in name.lower()]
        self.rate_limit = "; ".join(limits) or None

        if resp.status_code != 200 and strict:
            error = RateLimited if resp.status_code == 429 else TadoAPIError
            raise error(f"Tado returned {resp.status_code}", status=resp.status_code)

        if resp.status_code == 401:
            click.echo("Authentication expired. Please run 'tado auth' to re-authenticate.", err=True)
            return None

        if resp.status_code != 200:
            click.echo(f"API error {resp.status_code}: {resp.text}", err=True)
            return None

        return resp.json()

    def get_devices(self) -> list | None:
        """Fetch all devices in the home."""
        return self._request("GET", f"/homes/{self.home_id}/devices")

    def get_zones(self, strict: bool = False) -> list | None:
        """Get all zones/rooms with their devices. Raises TadoAPIError if strict."""
        return self._request("GET", f"/homes/{self.home_id}/zones", strict=strict)

    def get_zone_state(self, zone_id: int) -> dict | None:
        """Fetch the current state of a zone."""
        return self._request("GET", f"/homes/{self.home_id}/zones/{zone_id}/state")

    def get_zone_control(self, zone_id: int) -> dict | None:
        """Fetch the control configuration for a zone (includes heatingCircuit assignment)."""
        return self._request("GET", f"/homes/{self.home_id}/zones/{zone_id}/control")

    def get_day_report(self, zone_id: int, day: date) -> dict:
        """A zone's measurements for one day, about every 15 minutes. Raises TadoAPIError."""
        return self._request(
            "GET", f"/homes/{self.home_id}/zones/{zone_id}/dayReport?date={day.isoformat()}", strict=True
        )

    def get_home(self) -> dict | None:
        """Fetch home details."""
        return self._request("GET", f"/homes/{self.home_id}")
