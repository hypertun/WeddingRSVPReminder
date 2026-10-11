#!/bin/bash
# Convenient runner that automatically uses the virtual environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
SCRIPT="$SCRIPT_DIR/send_rsvp_messages.py"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "Virtual environment not found at $VENV_PYTHON."
    exit 1
fi

exec "$VENV_PYTHON" "$SCRIPT" "$@"
