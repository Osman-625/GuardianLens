#!/usr/bin/env bash
# Starts the GuardianLens API (port 8000) and the website (port 3000).
# Run it from a shell where the conda environment is active:
#     conda activate Guardianlens_venv
# (see environment.yml for how to create it). The API runs with that environment's Python.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [ -z "${CONDA_PREFIX:-}" ]; then
  echo "Activate the conda environment first: conda activate Guardianlens_venv" >&2
  exit 1
fi
trap 'kill 0' EXIT INT TERM
uvicorn api.main:app --reload --host localhost --port 8000 &
(
  cd frontend
  npm run dev
) &
wait
