.PHONY: install install-dev api web test lint typecheck secret-scan check

install:
	python -m pip install -e .
	npm ci

install-dev:
	python -m pip install -e ".[dev]"
	npm ci

# Run these from a terminal where the conda environment is active (conda activate Guardianlens_venv).
# --host localhost listens on IPv6 and IPv4. The default (IPv4 only) made every new connection from
# a browser wait about 2 s on Windows, where "localhost" resolves to IPv6 first.
api:
	uvicorn api.main:app --reload --reload-dir api --host localhost --port 8000

web:
	npm run dev -w frontend

test:
	pytest

lint:
	ruff check api scripts
	cd frontend && npm run lint

typecheck:
	mypy api
	cd frontend && npm run typecheck

secret-scan:
	python scripts/secret_scan.py

check: lint typecheck test secret-scan
