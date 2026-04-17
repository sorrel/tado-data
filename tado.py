#!/usr/bin/env python3
"""
Tado Data CLI
Report on Tado smart heating system status.
"""

import click

from commands.setup import ColouredGroup, auth_command, logout_command, status_command
from commands.battery import battery_command
from commands.zones import zones_command


@click.group(cls=ColouredGroup)
def cli():
    """Tado Data — reporting tool for Tado smart heating."""
    pass


# Setup & auth
cli.add_command(auth_command)
cli.add_command(logout_command)
cli.add_command(status_command)

# Reporting
cli.add_command(battery_command)
cli.add_command(zones_command)


if __name__ == "__main__":
    cli()
