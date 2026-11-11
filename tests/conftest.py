"""
Shared test fixtures.

Nothing here touches the Tado API — the whole suite is pure logic and
temporary files, per the "never hit live endpoints" rule in CLAUDE.md.
"""

from datetime import date

import pytest

# A fixed "today" so date-dependent assertions don't rot overnight.
TODAY = date(2026, 8, 25)


class FrozenDate(date):
    """A date whose today() is pinned to TODAY.

    Subclassing date (rather than faking it) keeps fromisoformat and
    arithmetic working exactly as the real thing.
    """

    @classmethod
    def today(cls):
        return TODAY


@pytest.fixture
def frozen_today(monkeypatch):
    """Pin date.today() in both modules that call it."""
    import commands.battery as battery_mod
    import core.storage as storage_mod

    monkeypatch.setattr(storage_mod, "date", FrozenDate)
    monkeypatch.setattr(battery_mod, "date", FrozenDate)
    return TODAY


@pytest.fixture
def history_file(tmp_path, monkeypatch):
    """Redirect battery history storage into a temp file.

    Guards the real stored_data/battery_history.json from the test run.
    """
    import core.storage as storage_mod

    path = tmp_path / "battery_history.json"
    monkeypatch.setattr(storage_mod, "BATTERY_HISTORY_FILE", str(path))
    return path


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    """Redirect tokens.json and its lock into a temp directory.

    Guards the real login from the test run.
    """
    import core.auth as auth_mod

    path = tmp_path / "tokens.json"
    monkeypatch.setattr(auth_mod, "TOKEN_FILE", path)
    monkeypatch.setattr(auth_mod, "TOKEN_LOCK_FILE", tmp_path / "tokens.json.lock", raising=False)
    return path


@pytest.fixture
def heat_store_dir(tmp_path, monkeypatch):
    """Redirect heat-check day reports and state into a temp directory.

    Guards the real stored_data/ from the test run.
    """
    import core.heat_store as heat_store_mod

    monkeypatch.setattr(heat_store_mod, "DAY_REPORTS_DIR", str(tmp_path / "day_reports"))
    monkeypatch.setattr(heat_store_mod, "HEAT_STATE_FILE", str(tmp_path / "heat_check.json"))
    return tmp_path
