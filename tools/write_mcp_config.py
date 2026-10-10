"""Regenerate `.mcp.json` with paths valid for the current machine.

`.mcp.json` has to carry absolute paths -- the MCP client launches the server directly and does not
resolve anything relative to the repo. That makes the file machine-specific, so moving the repo
breaks it. Rather than hand-editing three paths, run this.

    python tools/write_mcp_config.py

It writes nothing unless the Vibe-Trading clone and its virtualenv both exist, so a checkout without
the optional tooling simply reports what is missing instead of producing a config that fails at
startup.

The clone itself lives in gitignored `tools/vendor/` and is *not* part of the application. See
MIGRATION.md for how to recreate it, or skip it entirely -- nothing in `backend/` depends on it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR = REPO_ROOT / "tools" / "vendor"
SERVER = VENDOR / "Vibe-Trading" / "agent" / "mcp_server.py"

#: Interpreter inside the dedicated venv, on either platform.
PYTHON_CANDIDATES = (
    VENDOR / ".venv-vibe" / "Scripts" / "python.exe",  # Windows
    VENDOR / ".venv-vibe" / "bin" / "python",  # macOS / Linux
)


def main() -> int:
    missing: list[str] = []

    python = next((p for p in PYTHON_CANDIDATES if p.exists()), None)
    if python is None:
        missing.append(f"venv interpreter under {VENDOR / '.venv-vibe'}")
    if not SERVER.exists():
        missing.append(str(SERVER))

    if missing:
        print("Not writing .mcp.json -- optional tooling is not installed:")
        for item in missing:
            print(f"  missing: {item}")
        print("\nSee MIGRATION.md ('Optional: Vibe-Trading MCP server') to set it up, or ignore")
        print("this entirely -- the application does not depend on it.")
        return 1

    assert python is not None
    agent_dir = SERVER.parent
    config = {
        "mcpServers": {
            "vibe-trading": {
                "command": python.as_posix(),
                "args": [SERVER.as_posix()],
                "cwd": agent_dir.as_posix(),
                "env": {
                    "PYTHONPATH": agent_dir.as_posix(),
                    "PYTHONIOENCODING": "utf-8",
                },
            }
        }
    }

    target = REPO_ROOT / ".mcp.json"
    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target}")
    print(f"  interpreter: {python}")
    print(f"  server     : {SERVER}")
    print("\nVerify with: python tools/probe_mcp.py .mcp.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
