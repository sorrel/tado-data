"""
macOS notifications, through osascript.

The title and message are passed as arguments to the script rather than
written into it, so quotes or other characters in a room name can't break it.
The first notification may need allowing in System Settings → Notifications,
where macOS lists it under Script Editor.
"""

import subprocess

_SCRIPT = [
    "-e",
    "on run argv",
    "-e",
    "display notification (item 2 of argv) with title (item 1 of argv)",
    "-e",
    "end run",
]


class NotifyError(Exception):
    """The notification couldn't be shown."""


def notify(title: str, message: str) -> None:
    try:
        subprocess.run(
            ["osascript", *_SCRIPT, title, message], check=True, timeout=10, capture_output=True
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise NotifyError(str(error)) from error
