"""
Tado Data CLI
Report on Tado smart heating system status.
"""

import click

from tado_data.commands.battery import battery_command
from tado_data.commands.battery_history import battery_history_command
from tado_data.commands.battery_record import (
    battery_make_command,
    battery_reading_command,
    battery_replaced_command,
)
from tado_data.commands.heat_check import heat_check_command
from tado_data.commands.setup import ColouredGroup, auth_command, logout_command, status_command
from tado_data.commands.zones import zones_command


@click.group(cls=ColouredGroup)
def cli():
    """Tado Data — reporting tool for Tado smart heating."""


# Setup & auth
cli.add_command(auth_command)
cli.add_command(logout_command)
cli.add_command(status_command)

# Reporting
cli.add_command(battery_command)
cli.add_command(battery_history_command)
cli.add_command(battery_replaced_command)
cli.add_command(battery_reading_command)
cli.add_command(battery_make_command)
cli.add_command(zones_command)
cli.add_command(heat_check_command)
