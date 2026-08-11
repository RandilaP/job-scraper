#!/bin/bash

# Resolve the repository directory relative to this script so it works on the VM.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Activate the virtual environment
source "$SCRIPT_DIR/venv/bin/activate"

# Execute the runner script
python runner.py
