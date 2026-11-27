"""
A blank line before and after every command's output in the terminal.

Commands differ in whether they start or end with a blank line of their own,
so rather than each one adding its own, the CLI group wraps the whole run.
The wrapper counts the newlines at the end of everything written so far, on
stdout and stderr together, and never lets two blank lines run together. So a
command that already starts or ends with a blank line doesn't get a second.

It only applies in a terminal: piped output, the scheduled heat check's log
and tab completion are left exactly as they were.
"""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class _Spacing:
    """How many newlines end the output so far; 2 means a blank line."""

    def __init__(self) -> None:
        self.newlines = 0

    def trim(self, text: str) -> str:
        """Drop any leading newlines that would make a second blank line."""
        body = text.lstrip("\n")
        allowed = max(0, 2 - self.newlines)
        kept = min(len(text) - len(body), allowed)
        if body:
            self.newlines = len(body) - len(body.rstrip("\n"))
        else:
            self.newlines += kept
        return "\n" * kept + body


class _SpacedOutput:
    """A text stream that writes through `_Spacing`; anything else passes through."""

    def __init__(self, stream: Any, spacing: _Spacing) -> None:
        self._stream = stream
        self._spacing = spacing

    def write(self, text: Any) -> int:
        if isinstance(text, str):
            self._stream.write(self._spacing.trim(text))
            return len(text)
        return self._stream.write(text)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _SpacedInput:
    """stdin, noting that the Enter after an answer to a prompt ends a line."""

    def __init__(self, stream: Any, spacing: _Spacing) -> None:
        self._stream = stream
        self._spacing = spacing

    def readline(self, *args: Any) -> str:
        line = self._stream.readline(*args)
        self._spacing.newlines = 1
        return line

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def _is_terminal(stream: Any) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


@contextmanager
def spaced_output() -> Iterator[None]:
    """Put a blank line before and after everything written inside the block."""
    if not _is_terminal(sys.stdout):
        yield
        return

    spacing = _Spacing()
    saved = sys.stdout, sys.stderr, sys.stdin
    sys.stdout = _SpacedOutput(saved[0], spacing)
    if _is_terminal(saved[1]):
        sys.stderr = _SpacedOutput(saved[1], spacing)
    sys.stdin = _SpacedInput(saved[2], spacing)
    # The shell prompt's line has ended, so one newline here makes the blank line
    spacing.newlines = 1
    sys.stdout.write("\n")
    try:
        yield
    finally:
        sys.stdout.write("\n" * max(0, 2 - spacing.newlines))
        sys.stdout.flush()
        sys.stdout, sys.stderr, sys.stdin = saved
