# ==========================================================================
# AutoDev Architect — developer Makefile
#
# Every target is self-contained: it uses the project virtualenv (.venv)
# directly, so you do NOT need to `source .venv/bin/activate` first.
#
# Quick start:
#   make install     # backend venv + deps, frontend node deps
#   make test        # run the full backend + frontend test suites
#   make build       # production build of the frontend
#   make clean       # remove every generated artifact (tree stays git-clean)
#
# Run `make help` (or just `make`) for the full target list.
# ==========================================================================

# --- Tooling (override on the CLI, e.g. `make install PYTHON=python3.11`) ---
PYTHON       ?= python3
NPM          ?= npm
VENV         := .venv
VENV_BIN     := $(VENV)/bin
PY           := $(VENV_BIN)/python
PIP          := $(VENV_BIN)/pip
FRONTEND_DIR := frontend
PYTEST_PATHS := tests backend/tests

# Backend entrypoint (FastAPI via uvicorn)
APP          := backend.api.main:app
HOST         ?= 0.0.0.0
PORT         ?= 8000
COMPOSE      ?= docker compose -f infrastructure/docker-compose.yml

# Use one shell per recipe and fail fast.
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c
SHELL := bash

.DEFAULT_GOAL := help

# --------------------------------------------------------------------------
# Help
# --------------------------------------------------------------------------
.PHONY: help
help: ## Show this help message
	@echo "AutoDev Architect — make targets"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Override tools with VARS, e.g.: make install PYTHON=python3.11 PORT=9000"

# --------------------------------------------------------------------------
# Install
# --------------------------------------------------------------------------
.PHONY: install install-backend install-frontend install-dev venv

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

venv: $(VENV)/bin/activate ## Create the Python virtualenv (.venv) if missing

install: install-backend install-frontend ## Install backend + frontend dependencies

install-backend: venv ## Install backend runtime + test dependencies into .venv
	$(PIP) install -r backend/requirements.txt

install-frontend: ## Install frontend node dependencies
	cd $(FRONTEND_DIR) && $(NPM) install

install-dev: venv ## Install optional dev tools (black, ruff, mypy, pytest-cov)
	$(PIP) install black ruff mypy pytest-cov

# --------------------------------------------------------------------------
# Test
# --------------------------------------------------------------------------
.PHONY: test test-backend test-frontend coverage

test: test-backend test-frontend ## Run the full backend + frontend test suites

test-backend: ## Run the backend pytest suite with coverage gate (>=60%)
	$(PY) -m pytest $(PYTEST_PATHS) -q \
		--cov=backend --cov-report=term-missing --cov-fail-under=60

test-frontend: ## Run the frontend vitest suite
	cd $(FRONTEND_DIR) && $(NPM) test

coverage: ## Run backend tests with coverage (needs `make install-dev`)
	$(PY) -m pytest $(PYTEST_PATHS) \
		--cov=backend --cov-report=term-missing --cov-report=html

# --------------------------------------------------------------------------
# Lint / format / typecheck  (backend tools come from `make install-dev`)
# --------------------------------------------------------------------------
.PHONY: lint lint-backend lint-frontend format typecheck typecheck-backend typecheck-frontend

lint: lint-backend lint-frontend ## Lint backend (ruff) + frontend (eslint)

lint-backend: ## Lint backend with ruff
	$(PY) -m ruff check backend tests

lint-frontend: ## Lint frontend with eslint
	cd $(FRONTEND_DIR) && $(NPM) run lint

format: ## Auto-format backend with black + ruff --fix
	$(PY) -m black backend tests
	$(PY) -m ruff check --fix backend tests

typecheck: typecheck-backend typecheck-frontend ## Typecheck backend (mypy) + frontend (tsc)

typecheck-backend: ## Typecheck backend with mypy
	$(PY) -m mypy backend

typecheck-frontend: ## Typecheck frontend with tsc --noEmit
	cd $(FRONTEND_DIR) && $(NPM) run typecheck

# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
.PHONY: build build-frontend

build: build-frontend ## Production build (frontend). Backend ships as source.

build-frontend: ## Build the Next.js frontend for production
	cd $(FRONTEND_DIR) && $(NPM) run build

# --------------------------------------------------------------------------
# Run (development servers)
# --------------------------------------------------------------------------
.PHONY: run-backend run-frontend

run-backend: ## Start the FastAPI backend with autoreload
	$(PY) -m uvicorn $(APP) --reload --host $(HOST) --port $(PORT)

run-frontend: ## Start the Next.js dev server
	cd $(FRONTEND_DIR) && $(NPM) run dev

# --------------------------------------------------------------------------
# Container-first E0 workflow
# --------------------------------------------------------------------------
.PHONY: container-build container-up container-shell container-test container-check container-down container-logs docker-up docker-down run_secret_scanning security-scan

container-build: ## Build the backend dev/test container
	$(COMPOSE) build backend

container-up: ## Boot the backend container for E0 development
	$(COMPOSE) up --build backend

container-shell: ## Open a shell inside the backend dev/test container
	$(COMPOSE) run --rm backend sh

container-test: ## Run backend tests inside the backend container
	$(COMPOSE) run --rm backend pytest $(PYTEST_PATHS) -q \
		--cov=backend --cov-report=term-missing --cov-fail-under=60

run_secret_scanning: ## Run the repository secret scanner inside the backend container
	$(COMPOSE) run --rm backend python scripts/run_secret_scanning.py .

security-scan: run_secret_scanning ## Alias for local/container secret scanning

container-check: ## Run backend lint, typecheck, and tests inside the backend container
	$(COMPOSE) run --rm backend sh -lc '\
		python scripts/run_secret_scanning.py . && \
		ruff check backend tests && \
		mypy backend && \
		pytest $(PYTEST_PATHS) -q --cov=backend --cov-report=term-missing --cov-fail-under=60'

container-down: ## Tear down the Docker Compose stack
	$(COMPOSE) down

container-logs: ## Follow backend container logs
	$(COMPOSE) logs -f backend

docker-up: container-up ## Alias for container-up

docker-down: container-down ## Alias for container-down

# --------------------------------------------------------------------------
# CI parity: everything the pipelines run
# --------------------------------------------------------------------------
.PHONY: check check-backend check-frontend

check: check-backend check-frontend ## Run lint + typecheck + tests + build (CI parity)

check-backend: lint-backend typecheck-backend test-backend ## Backend CI checks

check-frontend: ## Frontend CI checks (lint, typecheck, test, build)
	cd $(FRONTEND_DIR) && $(NPM) run lint && $(NPM) run typecheck && $(NPM) test && $(NPM) run build

# --------------------------------------------------------------------------
# Clean — remove every generated artifact (these are all in .gitignore)
# --------------------------------------------------------------------------
.PHONY: clean clean-pyc clean-test clean-build clean-frontend distclean

clean: clean-pyc clean-test clean-build clean-frontend ## Remove generated build/test artifacts

clean-pyc: ## Remove Python bytecode and __pycache__
	find . -path ./.venv -prune -o -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -path ./.venv -prune -o -type f -name '*.py[cod]' -delete 2>/dev/null || true

clean-test: ## Remove pytest/coverage/lint caches and reports
	rm -rf .pytest_cache backend/.pytest_cache .ruff_cache .mypy_cache
	rm -rf .coverage coverage.xml htmlcov
	find tests/reports -type f ! -name '.gitkeep' -delete 2>/dev/null || true

clean-build: ## Remove Python packaging artifacts
	rm -rf build dist .eggs
	find . -path ./.venv -prune -o -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true

clean-frontend: ## Remove frontend build output (keeps node_modules)
	rm -rf $(FRONTEND_DIR)/.next $(FRONTEND_DIR)/out $(FRONTEND_DIR)/tsconfig.tsbuildinfo

distclean: clean ## clean + drop the virtualenv and frontend node_modules
	rm -rf $(VENV) $(FRONTEND_DIR)/node_modules
