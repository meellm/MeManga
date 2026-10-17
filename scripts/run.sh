#!/bin/bash
# MeManga launcher for Linux/macOS
# Runs in the caller's working directory, so relative paths
# (e.g. `export backup.json`) resolve where the command was typed.

# Locate project root without changing the working directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Activate venv if exists
if [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

PYTHON=python3
if [ -x "$PROJECT_DIR/venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/venv/bin/python"
fi

# Not `-m memanga`: that would search the caller's directory for modules.
# -I keeps it (and PYTHONPATH) out until the launcher has filtered them.
"$PYTHON" -I "$PROJECT_DIR/scripts/memanga_launcher.py" "$@"
