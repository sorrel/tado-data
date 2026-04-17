"""
Tado API client.

Handles authenticated requests to the Tado REST API v2.
"""

import click
import requests

from core.auth import get_access_token, device_code_flow

API_BASE = "https://my.tado.com/api/v2"


class TadoClient:
    """Client for the Tado REST API v2."""

    def __init__(self):
        self.session = requests.Session()
        self.home_id = None

    def connect(self) -> bool:
        """
        Authenticate and fetch the home ID.

        Returns True if connection is successful.
        """
        token = get_access_token()

        if not token:
            click.echo("No valid token found. Starting authorisation flow...")
            tokens = device_code_flow()
            if not tokens:
                return False
            token = tokens.get("access_token")

        self.session.headers.update({
            "Authorization": f"Bearer {token}",
        })

        # Fetch home ID
        me = self._request("GET", "/me")
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

    def _request(self, method: str, path: str) -> dict | list | None:
        """
        Make an authenticated API request.

        Returns parsed JSON response, or None on failure.
        """
        url = f"{API_BASE}{path}"
        try:
            resp = self.session.request(method, url)
        except requests.RequestException as e:
            click.echo(f"Request failed: {e}", err=True)
            return None

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

    def get_zones(self) -> list | None:
        """Fetch all zones (rooms) in the home."""
        return self._request("GET", f"/homes/{self.home_id}/zones")

    def get_zone_state(self, zone_id: int) -> dict | None:
        """Fetch the current state of a zone."""
        return self._request("GET", f"/homes/{self.home_id}/zones/{zone_id}/state")

    def get_zone_control(self, zone_id: int) -> dict | None:
        """Fetch the control configuration for a zone (includes heatingCircuit assignment)."""
        return self._request("GET", f"/homes/{self.home_id}/zones/{zone_id}/control")

    def get_home(self) -> dict | None:
        """Fetch home details."""
        return self._request("GET", f"/homes/{self.home_id}")
