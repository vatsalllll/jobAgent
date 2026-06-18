#!/bin/bash
# Job Agent — Start Script
# Starts n8n (Docker) and FastAPI (local Python)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "  Job Agent — Starting"
echo "============================================"
echo ""

# Check .env
if [ ! -f "$SCRIPT_DIR/backend/.env" ]; then
    echo "⚠️  No .env found. Creating from .env.example..."
    cp "$SCRIPT_DIR/backend/.env.example" "$SCRIPT_DIR/backend/.env"
    echo "❌ Please edit backend/.env with your API keys, then re-run."
    exit 1
fi

# Source env vars
set -a
source "$SCRIPT_DIR/backend/.env"
set +a

# Start n8n
echo "🐳 Starting n8n (Docker)..."
cd "$SCRIPT_DIR/n8n"
docker compose up -d
echo "   n8n running at http://localhost:5678"
echo ""

# Start FastAPI
echo "🚀 Starting FastAPI backend..."
cd "$SCRIPT_DIR/backend"
source venv/bin/activate
echo "   FastAPI running at http://localhost:8000"
echo "   API docs at http://localhost:8000/docs"
echo ""
echo "============================================"
echo "  Ready. Press Ctrl+C to stop FastAPI."
echo "  (n8n continues in Docker — stop with: docker compose -f n8n/docker-compose.yml down)"
echo "============================================"

python main.py
