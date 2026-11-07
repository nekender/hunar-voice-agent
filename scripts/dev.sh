#!/usr/bin/env bash
# Local run: serves the built frontend and the API on :8080. Reads secrets from .env (gitignored).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
export DATA_DIR="${DATA_DIR:-./data}" RECORD_WEBHOOK_URL="${RECORD_WEBHOOK_URL:-http://localhost:8080/sink/records}"
cd backend && exec ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
