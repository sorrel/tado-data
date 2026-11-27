"""
Table layout shared by the reports: cells padded before they are coloured,
section titles, column headers and the rule under them.
"""

from typing import Any

import click

# A section's title in a report.
SECTION_STYLE: dict[str, Any] = {"fg": "bright_cyan", "bold": True}


def cell(value: object, width: int, align: str = "<", **style: Any) -> str:
    """Pad a table cell first, then colour it, so the colour codes don't upset the columns."""
    padded = f"{value!s:{align}{width}}"
    return click.style(padded, **style) if style and padded else padded


def echo_header(header: str) -> None:
    """A table's column header and the rule under it. HEADER starts with its two-space indent."""
    click.echo(click.style(header, fg="bright_white", bold=True))
    click.echo(click.style("  " + "─" * (len(header) - 2), fg="bright_black"))


def echo_section(title: str, header: str) -> None:
    """A section title, then its column header and the rule under it."""
    click.echo(click.style(f"  {title}", **SECTION_STYLE))
    echo_header(header)


def count(number: int, noun: str) -> str:
    """ "1 set", "2 sets"."""
    return f"{number} {noun}{'s' if number != 1 else ''}"
