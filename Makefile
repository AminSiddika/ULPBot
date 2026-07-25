.PHONY: help build up down logs shell lint format typecheck test

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  build       Build Docker images"
	@echo "  up          Start all services (detached)"
	@echo "  down        Stop all services"
	@echo "  logs        Tail bot logs"
	@echo "  shell       Open shell in bot container"
	@echo "  lint        Run ruff linter"
	@echo "  format      Run ruff formatter"
	@echo "  typecheck   Run mypy type checker"
	@echo "  test        Run tests with coverage"

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f bot

shell:
	docker compose exec bot bash

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

typecheck:
	mypy src/ --ignore-missing-imports

test:
	pytest
