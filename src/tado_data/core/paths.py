"""Where the project keeps its local files: the login and stored_data/, both gitignored."""

from pathlib import Path

# src/tado_data/core/paths.py: three folders up is the project itself.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
STORED_DATA_DIR = str(PROJECT_ROOT / "stored_data")
TOKEN_FILE = PROJECT_ROOT / "tokens.json"
