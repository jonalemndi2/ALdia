"""Lanzador estable del servidor MCP desde cualquier directorio."""

from pathlib import Path
import sys


MCP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MCP_DIR))

from aldia_mcp.server import main  # noqa: E402


if __name__ == "__main__":
    main()
