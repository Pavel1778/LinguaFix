.PHONY: help install uninstall test lint format typecheck check build-deb smoke-test zero-config clean dev

PYTHON ?= python3
VENV ?= .venv
VENV_PY := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(VENV_PY):
	$(PYTHON) -m venv $(VENV)

dev: $(VENV_PY) ## Create a virtualenv and install dev dependencies
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -e ".[dev]"

install: ## Run the system installer (bash install.sh)
	bash install.sh

uninstall: ## Run the system uninstaller (bash uninstall.sh)
	bash uninstall.sh

test: ## Run the test suite with coverage
	$(VENV_PY) -m pytest tests/ -q --cov=linguafix --cov-report=term-missing

lint: ## Run ruff and black checks
	$(VENV)/bin/ruff check .
	$(VENV)/bin/black --check .

format: ## Auto-format the code with ruff and black
	$(VENV)/bin/ruff check . --fix
	$(VENV)/bin/black .

typecheck: ## Run mypy in strict mode
	$(VENV)/bin/mypy --strict .

check: lint typecheck test ## Run lint, typecheck and tests

build-deb: ## Build a .deb package
	bash scripts/build_deb.sh

smoke-test: ## Install the built .deb in a clean Debian container and run the CLI
	bash scripts/smoke_test.sh
zero-config: ## Prove the .deb installs with no manual step (no usermod, no enable)
	bash scripts/deb_selfsufficiency_test.sh

clean: ## Remove build artifacts and caches
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
