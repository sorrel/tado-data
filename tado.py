"""
Run the Tado Data CLI from the project folder: `uv run python tado.py <command>`.

The code is in src/tado_data/; this stays here so the launchd job and the
shell completion, which both run tado.py, keep working.
"""

from tado_data.cli import cli

if __name__ == "__main__":
    cli()
