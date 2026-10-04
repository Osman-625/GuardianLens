.PHONY: install install-dev api web test lint typecheck secret-scan check

install:
	python -m pip install -r requirements.txt
	cd frontend && npm ci

install-dev:
	python -m pip install -r requirements-dev.txt
	cd frontend && npm ci

api:
	uvicorn api.main:app --reload --port 8000
	cd frontend && npm run dev

web:
	cd frontend && npm run dev

test:
	pytest

lint:
	ruff check api ml scripts
	cd frontend && npm run lint

typecheck:
	mypy api ml/src/guardianlens_ml
	cd frontend && npm run typecheck

secret-scan:
	python scripts/secret_scan.py

check: lint typecheck test secret-scan
