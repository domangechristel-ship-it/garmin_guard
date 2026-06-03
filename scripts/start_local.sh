#!/bin/bash
set -e

# Kill whatever is on port 8000 (by port, not by name — avoids self-matching)
lsof -ti:8000 | xargs kill 2>/dev/null || true

# Start API and capture its PID
uvicorn package_folder.api_file:app --port 8000 &
API_PID=$!

# Kill API cleanly when this script exits (Ctrl+C, error, or normal exit)
trap "kill $API_PID 2>/dev/null || true" EXIT

echo "Waiting for API..."
until curl -s http://localhost:8000/health > /dev/null 2>&1; do sleep 1; done
echo "API ready — starting Streamlit"

API_URL=http://localhost:8000 streamlit run streamlit_app.py
