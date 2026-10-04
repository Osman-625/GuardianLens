#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
trap 'kill 0' EXIT INT TERM
uvicorn api.main:app --reload --port 8000 &
(
  cd frontend
  npm run dev
) &
wait
