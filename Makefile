# AgenticOS — top-level developer commands.
# All commands assume Docker + Docker Compose v2 are installed.

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

PYTHON ?= python3
VENV   ?= .venv
PIP    := $(VENV)/bin/pip
PY     := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest
RUFF   := $(VENV)/bin/ruff
MYPY   := $(VENV)/bin/mypy

SERVICES := shared api_gateway agent_runtime llm_gateway tool_registry knowledge_svc memory_svc worker

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
.PHONY: help
help: ## Show this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\nTargets:\n"} \
		/^[a-zA-Z0-9_.-]+:.*##/ {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Local Python env (for running tests / linters outside Docker)
# ---------------------------------------------------------------------------
.PHONY: venv
venv: $(VENV)/bin/activate ## Create local virtualenv.

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip wheel

.PHONY: install
install: venv ## Install all Python services (editable) into the venv.
	$(PIP) install -e ./services/shared
	@for svc in api_gateway agent_runtime llm_gateway tool_registry knowledge_svc memory_svc worker ; do \
		echo "==> installing $$svc" ; \
		$(PIP) install -e ./services/$$svc ; \
	done
	$(PIP) install -r requirements-dev.txt

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
.PHONY: lint
lint: ## Run ruff lint across all python services.
	$(RUFF) check services/

.PHONY: fmt
fmt: ## Auto-format with ruff.
	$(RUFF) format services/
	$(RUFF) check --fix services/

.PHONY: typecheck
typecheck: ## Run mypy.
	$(MYPY) services/

.PHONY: test
test: ## Run unit tests.
	$(PYTEST) services/ -q

.PHONY: cov
cov: ## Run unit tests with coverage report.
	$(PYTEST) services/ --cov=services --cov-report=term-missing --cov-report=xml

# ---------------------------------------------------------------------------
# Docker stack
# ---------------------------------------------------------------------------
.PHONY: dev
dev: ## Bring up the full dev stack (compose).
	docker compose up -d --build
	@echo "Waiting for services..."
	@sleep 5
	$(MAKE) migrate
	@echo "Stack is up. Web UI: http://localhost:$${WEB_UI_PORT:-3000} | API: http://localhost:$${API_GATEWAY_PORT:-8080}"

.PHONY: down
down: ## Stop the stack.
	docker compose down

.PHONY: nuke
nuke: ## Stop the stack AND delete all data volumes.
	docker compose down -v

.PHONY: logs
logs: ## Tail logs.
	docker compose logs -f --tail=200

.PHONY: ps
ps: ## Show service status.
	docker compose ps

.PHONY: smoke
smoke: ## Hit /healthz on each service.
	bash scripts/smoke.sh

.PHONY: pull-models
pull-models: ## Pull default Ollama models.
	bash scripts/pull_models.sh

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
.PHONY: migrate
migrate: ## Apply Alembic migrations against the running compose stack.
	docker compose run --rm api-gateway alembic upgrade head

.PHONY: makemigration
makemigration: ## Autogenerate a new migration. Usage: make makemigration M="message"
	docker compose run --rm api-gateway alembic revision --autogenerate -m "$(M)"

.PHONY: seed
seed: ## Seed dev data.
	docker compose run --rm api-gateway python -m scripts.seed
