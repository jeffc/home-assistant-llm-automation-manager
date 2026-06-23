#!/bin/bash
set -e

# Go to the workspace directory
cd "$(dirname "$0")"

# Set up virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install HA core and its dependencies in editable mode if not already installed
if ! pip show homeassistant >/dev/null 2>&1; then
    echo "Installing Home Assistant Core dependencies (this may take a few minutes)..."
    pip install --upgrade pip
    cd core
    pip install -e .
    cd ..
fi

# Run Home Assistant
echo "Starting Home Assistant..."
hass -c config
