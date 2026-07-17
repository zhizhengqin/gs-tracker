#!/bin/bash
set -e

source .venv/bin/activate

echo "=== Running GS-Tracker pipeline ==="
python src/main.py --run-now

echo "=== Starting web server ==="
uvicorn src.web:app --host 0.0.0.0 --port 8000
