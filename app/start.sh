#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -q -r app/backend/requirements.txt

if [[ ! -d app/frontend/node_modules ]]; then
  npm --prefix app/frontend install
fi

npm --prefix app/frontend run build
exec .venv/bin/uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
