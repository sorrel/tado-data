"""
Tests for the Tado login: saving, refreshing and locking tokens.

requests.post is always stubbed, so nothing here reaches Tado.
"""

import fcntl
import json
import stat

import pytest
import requests

import core.auth as auth
import core.client as client_mod
from core.client import TadoClient


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


def _rotating_post(sent):
    """A token endpoint that rotates refresh-N into refresh-(N+1)."""

    def post(url, data=None, timeout=None):
        sent.append(data["refresh_token"])
        n = len(sent) + 1
        return FakeResponse(200, {"access_token": f"access-{n}", "refresh_token": f"refresh-{n}"})

    return post


@pytest.fixture
def old_token(token_file):
    token_file.write_text(json.dumps({"access_token": "a", "refresh_token": "old"}))
    return token_file


# --- saving ------------------------------------------------------------------


def test_save_tokens_is_atomic_and_private(old_token, monkeypatch):
    # fsync fails after the new text is written: writing in place would already
    # have replaced the old login
    def broken_fsync(fd):
        raise OSError("disk full")

    monkeypatch.setattr(auth.os, "fsync", broken_fsync)
    with pytest.raises(OSError):
        auth.save_tokens({"refresh_token": "new"})
    assert json.loads(old_token.read_text())["refresh_token"] == "old"


def test_saved_tokens_are_owner_only(token_file):
    auth.save_tokens({"refresh_token": "new"})
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


# --- refreshing --------------------------------------------------------------


def test_successful_refresh_saves_the_rotated_token(old_token, monkeypatch):
    sent = []
    monkeypatch.setattr(auth.requests, "post", _rotating_post(sent))

    assert auth.get_access_token() == "access-2"
    assert json.loads(old_token.read_text())["refresh_token"] == "refresh-2"


def test_no_token_file_means_login_needed(token_file):
    with pytest.raises(auth.LoginNeeded):
        auth.get_access_token()


def test_rejected_refresh_means_login_needed(old_token, monkeypatch):
    monkeypatch.setattr(auth.requests, "post", lambda *a, **k: FakeResponse(400, {"error": "invalid_grant"}))
    with pytest.raises(auth.LoginNeeded):
        auth.get_access_token()


def test_network_failure_is_not_login_needed(old_token, monkeypatch):
    def offline(*a, **k):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(auth.requests, "post", offline)
    with pytest.raises(auth.AuthNetworkError):
        auth.get_access_token()
    assert json.loads(old_token.read_text())["refresh_token"] == "old"


def test_server_error_is_a_network_failure(old_token, monkeypatch):
    monkeypatch.setattr(auth.requests, "post", lambda *a, **k: FakeResponse(503))
    with pytest.raises(auth.AuthNetworkError):
        auth.get_access_token()


# --- locking -----------------------------------------------------------------


def test_held_lock_gives_up_after_timeout(old_token, monkeypatch):
    monkeypatch.setattr(auth, "TOKEN_LOCK_TIMEOUT", 0.2)
    monkeypatch.setattr(auth.requests, "post", lambda *a, **k: pytest.fail("refreshed without the lock"))
    with open(auth.TOKEN_LOCK_FILE, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(auth.TokenLockBusy):
            auth.get_access_token()


def test_token_is_read_inside_the_lock(old_token, monkeypatch):
    """A second run must refresh with the token the first run saved."""
    sent = []
    monkeypatch.setattr(auth.requests, "post", _rotating_post(sent))

    auth.get_access_token()
    auth.get_access_token()

    assert sent == ["old", "refresh-2"]


# --- connecting --------------------------------------------------------------


def test_non_interactive_connect_never_starts_device_login(token_file, monkeypatch):
    monkeypatch.setattr(client_mod, "device_code_flow", lambda: pytest.fail("prompted"))
    with pytest.raises(auth.LoginNeeded):
        TadoClient().connect(interactive=False)


def test_interactive_connect_reports_network_failure_without_prompting(old_token, monkeypatch, capsys):
    def offline(*a, **k):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(auth.requests, "post", offline)
    monkeypatch.setattr(client_mod, "device_code_flow", lambda: pytest.fail("prompted"))

    assert TadoClient().connect() is False
    assert "login server" in capsys.readouterr().err
