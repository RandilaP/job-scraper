#!/bin/bash

# Navigate to the workspace directory
cd "/Users/randila/WORKSPACE/Jobhelpers/job extractor v2.1" || exit 1

# Activate the virtual environment
source venv/bin/activate

# Execute the runner script
python runner.py
