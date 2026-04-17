"""
Setup and authentication commands.
"""

import textwrap

import click

from core.auth import device_code_flow, clear_tokens, load_tokens
from core.client import TadoClient


class ColouredGroup(click.Group):
    """Click group with coloured command listing."""

    def format_commands(self, ctx, formatter):
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None or cmd.hidden:
                continue
            help_text = cmd.get_short_help_str(limit=150)
            commands.append((subcommand, help_text))

        if commands:
            col_width = max(len(name) for name, _ in commands) + 2
            # write_text adds current_indent (2) + our "  " prefix = 4 spaces before name
            help_col = 4 + col_width
            help_indent = " " * help_col
            available = max(formatter.width - help_col, 20)
            with formatter.section("Commands"):
                for name, help_text in commands:
                    padding = " " * (col_width - len(name))
                    name_str = click.style(name, fg="cyan")
                    lines = textwrap.wrap(help_text, width=available)
                    first = lines[0] if lines else ""
                    rest = ("\n" + help_indent).join(lines[1:])
                    full = (first + "\n" + help_indent + rest) if rest else first
                    formatter.write(f"    {name_str}{padding}{full}\n")


@click.command("auth")
def auth_command():
    """Authenticate with Tado (OAuth2 device code flow)."""
    tokens = device_code_flow()
    if tokens:
        click.echo()
        click.echo("Token saved. You can now use other commands.")


@click.command("logout")
def logout_command():
    """Remove saved authentication tokens."""
    clear_tokens()
    click.echo("Tokens cleared.")


@click.command("status")
def status_command():
    """Show connection status and home info."""
    tokens = load_tokens()
    if not tokens:
        click.echo(click.style("Not authenticated.", fg="red"))
        click.echo("Run 'tado auth' to authenticate.")
        return

    client = TadoClient()
    if not client.connect():
        return

    home = client.get_home()
    if not home:
        return

    click.echo(click.style("Connected to Tado", fg="green"))
    click.echo(f"  Home:     {home.get('name', 'Unknown')}")
    click.echo(f"  Home ID:  {client.home_id}")

    address = home.get("contactDetails", {}).get("name", "")
    if address:
        click.echo(f"  Contact:  {address}")

    # Show zone count
    zones = client.get_zones()
    if zones:
        click.echo(f"  Zones:    {len(zones)}")

    # Show device count
    devices = client.get_devices()
    if devices:
        click.echo(f"  Devices:  {len(devices)}")
