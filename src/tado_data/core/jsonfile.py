"""
Reading and saving the local JSON files in stored_data/.

Every file there is local only and can't be rebuilt from Tado, so a damaged
file stops the command rather than being read as empty (the next save would
overwrite the real data), and a save never leaves a half-written file.
"""

import json
import os
import shutil

import click


class DamagedFile(click.ClickException):
    """A saved file can't be read. Carrying on would overwrite it."""


def load_json(path: str) -> dict:
    """The file's contents, {} if it doesn't exist. Raises DamagedFile if it can't be read."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError as error:  # bad JSON, or bytes that aren't text
        raise DamagedFile(
            f"{path} is damaged, so nothing has been changed. "
            f"Restore it from {path}.bak or your own backup. ({error})"
        ) from error


def save_json(path: str, data: dict) -> None:
    """Save so that a failure part-way leaves the file intact, keeping the last version as .bak."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        shutil.copy2(path, f"{path}.bak")
    os.replace(temporary, path)
