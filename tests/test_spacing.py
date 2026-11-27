"""
Tests for the blank line before and after every command's output.

Streams are StringIOs pretending to be terminals; nothing reaches Tado.
"""

import io
import sys

import click
import pytest

from tado_data.core.spacing import spaced_output


class FakeTerminal(io.StringIO):
    def isatty(self):
        return True


def _terminal(monkeypatch):
    """Make stdout and stderr one fake terminal (inside the test, after pytest's capture)."""
    out = FakeTerminal()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", out)
    return out


def _run(*lines):
    with spaced_output():
        for line in lines:
            click.echo(line)


def test_adds_a_blank_line_before_and_after(monkeypatch):
    terminal = _terminal(monkeypatch)
    _run("Tokens cleared.")
    assert terminal.getvalue() == "\nTokens cleared.\n\n"


def test_never_doubles_a_blank_line_the_command_already_prints(monkeypatch):
    terminal = _terminal(monkeypatch)
    _run("", "Header", "row", "")
    assert terminal.getvalue() == "\nHeader\nrow\n\n"


def test_keeps_blank_lines_between_sections(monkeypatch):
    terminal = _terminal(monkeypatch)
    _run("one", "", "two")
    assert terminal.getvalue() == "\none\n\ntwo\n\n"


def test_errors_on_stderr_count_towards_the_spacing(monkeypatch):
    terminal = _terminal(monkeypatch)
    with spaced_output():
        click.echo("Request failed", err=True)
        click.echo("", err=True)
    assert terminal.getvalue() == "\nRequest failed\n\n"


def test_an_answered_prompt_ends_its_line(monkeypatch):
    terminal = _terminal(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO("Duracell\n"))
    with spaced_output():
        make = click.prompt("Make", default="", show_default=False)
    assert make == "Duracell"
    # The terminal echoes the Enter, so only one more newline is needed
    assert terminal.getvalue() == "\nMake: \n"


def test_leaves_piped_output_alone(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    _run("plain")
    assert out.getvalue() == "plain\n"


def test_restores_the_streams_after_an_exit(monkeypatch):
    terminal = _terminal(monkeypatch)
    with pytest.raises(SystemExit), spaced_output():
        click.echo("bye")
        raise SystemExit(1)
    assert sys.stdout is terminal
    assert terminal.getvalue() == "\nbye\n\n"
