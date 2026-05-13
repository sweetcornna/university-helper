.PHONY: help setup build start stop restart logs logs-app logs-db ps test test-backend test-frontend lint backup deploy clean precommit

COMPOSE := docker compose -f docker-compose.server.yml -p university-helper

help:
	@echo "University Helper — make targets"
	@echo ""
	@echo "Setup:"
	@echo "  make setup          Bootstrap local env (.env + tooling)"
	@echo "  make build          Build app image"
	@echo "  make precommit      Install pre-commit hooks"
	@echo ""
	@echo "Run:"
	@echo "  make start          Start docker-compose stack (app + postgres)"
	@echo "  make stop           Stop stack"
	@echo "  make restart        Restart stack"
	@echo "  make ps             Show services"
	@echo "  make logs           Tail all logs"
	@echo "  make logs-app       Tail backend (app) logs"
	@echo "  make logs-db        Tail postgres logs"
	@echo ""
	@echo "Quality:"
	@echo "  make test           Run all tests (backend + frontend)"
	@echo "  make test-backend   Backend pytest"
	@echo "  make test-frontend  Frontend vitest"
	@echo "  make lint           Run all linters (ruff + eslint)"
	@echo ""
	@echo "Ops:"
	@echo "  make backup         Run scripts/db_backup.sh"
	@echo "  make clean          Stop stack + prune dangling images"

setup:
	@bash scripts/setup.sh

build:
	$(COMPOSE) build app

precommit:
	pre-commit install

start:
	$(COMPOSE) up -d
	@echo "Services started. App on http://127.0.0.1:8000"

stop:
	$(COMPOSE) down

restart: stop start

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=200

logs-app:
	$(COMPOSE) logs -f --tail=200 app

logs-db:
	$(COMPOSE) logs -f --tail=200 postgres

test: test-backend test-frontend

test-backend:
	cd backend && pytest -q

test-frontend:
	cd frontend && npm run test -- --run

lint:
	cd backend && ruff check app/ && ruff format --check app/
	cd frontend && npm run lint

backup:
	@bash scripts/db_backup.sh

clean:
	$(COMPOSE) down
	docker image prune -f
