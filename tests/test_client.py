"""
Tests for TadoClient's requests.

The session's request method is replaced by a stub, so nothing reaches Tado.
"""

from datetime import date

import pytest
import requests

import core.client as client_mod
from core.client import RateLimited, TadoAPIError, TadoClient


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


def _client(response=None, error=None, seen=None):
    client = TadoClient()
    client.home_id = 42

    def request(method, url, timeout=None):
        if seen is not None:
            seen.append(url)
        if error:
            raise error
        return response

    client.session.request = request
    return client


def test_strict_request_raises_rate_limited_on_429():
    with pytest.raises(RateLimited) as caught:
        _client(FakeResponse(429))._request("GET", "/x", strict=True)
    assert caught.value.status == 429


def test_strict_request_raises_on_server_error():
    with pytest.raises(TadoAPIError) as caught:
        _client(FakeResponse(500))._request("GET", "/x", strict=True)
    assert caught.value.status == 500
    assert not isinstance(caught.value, RateLimited)


def test_strict_request_wraps_network_errors():
    with pytest.raises(TadoAPIError) as caught:
        _client(error=requests.ConnectionError("no route"))._request("GET", "/x", strict=True)
    assert caught.value.status is None


def test_non_strict_request_still_returns_none(capsys):
    assert _client(FakeResponse(500))._request("GET", "/x") is None
    assert "API error 500" in capsys.readouterr().err


def test_day_report_path_and_date():
    seen = []
    report = _client(FakeResponse(200, {"zoneType": "HEATING"}), seen=seen).get_day_report(
        12, date(2026, 11, 10)
    )
    assert report == {"zoneType": "HEATING"}
    assert seen[0].endswith("/homes/42/zones/12/dayReport?date=2026-11-10")


def test_rate_limit_headers_are_kept():
    client = _client(
        FakeResponse(200, {}, headers={"RateLimit-Remaining": "19000", "Content-Type": "x"})
    )
    client._request("GET", "/x")
    assert client.rate_limit == "RateLimit-Remaining=19000"


def test_non_interactive_connect_raises_when_account_lookup_fails(monkeypatch):
    monkeypatch.setattr(client_mod, "get_access_token", lambda: "token")
    with pytest.raises(TadoAPIError):
        _client(FakeResponse(503)).connect(interactive=False)


def test_strict_zones_raise_instead_of_returning_none():
    with pytest.raises(TadoAPIError):
        _client(FakeResponse(503)).get_zones(strict=True)
