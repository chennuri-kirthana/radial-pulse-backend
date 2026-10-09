# Radial Pulse backend — every command the team needs.  `make help` lists them.
# Python runs through uv (https://docs.astral.sh/uv/): no global installs, no manual venv.

.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help
help: ## Show this list
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------ setup
.PHONY: install
install: ## Install Python dependencies (.venv)
	$(UV) sync

.PHONY: lock
lock: ## Refresh uv.lock after changing pyproject.toml (commit it)
	$(UV) lock

.PHONY: db
db: ## Start local PostgreSQL 16 (docker)
	docker compose up -d postgres

.PHONY: db-reset
db-reset: ## Delete the local database and start fresh
	docker compose down -v
	docker compose up -d postgres

# ------------------------------------------------------------------ run
.PHONY: migrate
migrate: ## Apply all migrations (owner login)
	$(UV) run alembic upgrade head

.PHONY: dev
dev: ## Run the API with reload on http://localhost:8000/docs
	$(UV) run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: up
up: ## Database + migrations + API, all in docker
	docker compose --profile api up --build

.PHONY: create-admin
create-admin: ## First Platform Administrator: make create-admin EMAIL=you@x.com NAME="You"
	$(UV) run python -m app.cli create-platform-admin --email "$(EMAIL)" --name "$(NAME)"

# ------------------------------------------------------------------ checks
.PHONY: lint
lint: ## ruff lint
	$(UV) run ruff check .

.PHONY: format
format: ## ruff format (writes files)
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

.PHONY: format-check
format-check: ## ruff format check (CI)
	$(UV) run ruff format --check .

.PHONY: typecheck
typecheck: ## mypy --strict
	$(UV) run mypy

.PHONY: test
test: ## Fast tests (SQLite)
	$(UV) run pytest -m 'not integration'

.PHONY: sdk-test
sdk-test: ## Internal SDK (sdk/central-client): tests + types
	$(UV) run --directory sdk/central-client --locked pytest
	$(UV) run --directory sdk/central-client --locked mypy

.PHONY: integration-test
integration-test: ## Full suite on PostgreSQL (needs TEST_DATABASE_URL)
	$(UV) run pytest

.PHONY: schema-test
schema-test: ## Database v15 rules (db/tests ported to pytest) on PostgreSQL (needs TEST_DATABASE_URL)
	$(UV) run pytest tests/schema_v15

.PHONY: check
check: lint format-check typecheck test sdk-test contract-check ## Everything CI checks except PostgreSQL

.PHONY: audit-deps
audit-deps: ## Known vulnerabilities in dependencies
	$(UV) run pip-audit

# ------------------------------------------------------------------ database changes
.PHONY: migration
migration: ## New EMPTY migration, written by hand (no autogenerate): make migration NAME="add chat"
	$(UV) run alembic revision -m "$(NAME)"

# ------------------------------------------------------------------ API contract
.PHONY: openapi
openapi: ## Regenerate openapi/openapi.json (commit it with your change)
	$(UV) run python -m app.openapi_export openapi/openapi.json

.PHONY: contract-check
contract-check: ## Fail if openapi/openapi.json is out of date
	$(UV) run python -m app.openapi_export --check openapi/openapi.json

# ------------------------------------------------------------------ docker
.PHONY: docker-build
docker-build: ## Build the API image
	docker build -t radial-pulse-api:local .

# ------------------------------------------------------------------ lambda
.PHONY: lambda-zip
lambda-zip: ## Lambda ZIP (Linux wheels, Python 3.12): make lambda-zip [ARCH=arm64] → dist/lambda/
	$(UV) run python scripts/lambda/build_zip.py --arch $(or $(ARCH),x86_64)
