"""
Tests for the launchd schedule template. Nothing is installed or loaded.
"""

import plistlib
from pathlib import Path

TEMPLATE = Path(__file__).parent.parent / "tools" / "heat-check.plist.template"


def _rendered():
    text = TEMPLATE.read_text()
    for name, value in {"__UV__": "/opt/uv", "__REPO__": "/repo", "__LOG__": "/log"}.items():
        text = text.replace(name, value)
    return plistlib.loads(text.encode())


def test_runs_scheduled_heat_check_through_uv():
    plist = _rendered()
    assert plist["ProgramArguments"] == [
        "/opt/uv", "run", "--directory", "/repo", "python", "tado.py", "heat-check", "--scheduled",
    ]


def test_first_run_is_at_seven_with_later_runs_for_a_mac_switched_on_late():
    """A Mac that was off at 07:00 gets checked at the next slot; extra runs make no requests."""
    times = [(slot["Hour"], slot.get("Minute", 0)) for slot in _rendered()["StartCalendarInterval"]]
    assert times[0] == (7, 0)
    assert len(times) >= 4
    assert max(hour for hour, _ in times) >= 19


def test_does_not_run_at_login():
    """At login the network may not be up yet; a failure notification then would cry wolf."""
    assert _rendered().get("RunAtLoad", False) is False


def test_installer_sends_a_test_notification():
    """macOS may hide notifications until allowed; find out at install, not weeks later."""
    script = (TEMPLATE.parent / "install-heat-check.sh").read_text()
    assert "display notification" in script or "core.notify" in script
