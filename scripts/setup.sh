#!/bin/bash
set -e

echo "=== GS-Tracker setup ==="

python -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from template. Please edit it with your API keys."
fi

mkdir -p data/raw data/db output/reports

echo "Setup complete. Activate venv with: source .venv/bin/activate"
