#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --reload
