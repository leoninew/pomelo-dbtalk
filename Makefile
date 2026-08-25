.DEFAULT_GOAL := help

UV ?= uv
DOCKER ?= docker
IMAGE_NAME ?= dbtalk
IMAGE_TAG ?= latest
IMAGE := $(IMAGE_NAME):$(IMAGE_TAG)
CHECK_FIX := $(filter 1 true yes,$(fix))
RUFF_CHECK_ARGS :=
RUFF_FORMAT_ARGS := --check
TEST_COV_ARGS :=

ifneq ($(CHECK_FIX),)
RUFF_CHECK_ARGS := --fix
RUFF_FORMAT_ARGS :=
endif

ifneq ($(filter 1 true yes,$(cov)),)
TEST_COV_ARGS := --cov=dbtalk --cov-report=term-missing:skip-covered --cov-report=html
endif

.PHONY: help deps install check test release docker-build docker-smoke

help: ## Show available targets.
	@echo "Usage: make <target> [IMAGE_NAME=registry/dbtalk] [IMAGE_TAG=1.0.0]"
	@echo ""
	@echo "Targets:"
	@echo "  deps          Sync locked development dependencies"
	@echo "  install       Install the CLI and synchronize agent plugins"
	@echo "  check         Run Ruff and Mypy quality checks (fix=1 enables fixes)"
	@echo "  test          Run unit tests (cov=1 enables coverage reports)"
	@echo "  release       Build source and wheel distributions"
	@echo "  docker-build  Build the runtime container image"
	@echo "  docker-smoke  Run the image entrypoint with --version"

deps: ## Sync all locked development dependencies without installing the project.
	$(UV) sync --all-groups --locked --no-install-project

install: ## Install the CLI and synchronize agent plugins.
	$(UV) run python scripts/release.py plugin check
	$(UV) tool install --editable . --force
	dbtalk --version
	$(UV) run python scripts/release.py plugin apply

check: ## Run Ruff and Mypy checks without tests; use fix=1 to fix Ruff issues.
	$(UV) run ruff format $(RUFF_FORMAT_ARGS) src tests
	$(UV) run ruff check $(RUFF_CHECK_ARGS) src tests
	$(UV) run mypy src tests

test: ## Run unit tests; use cov=1 to collect coverage.
	$(UV) run pytest $(TEST_COV_ARGS)
	$(UV) run python scripts/test_release.py

release: ## Build source and wheel distributions.
	$(UV) build

docker-build: ## Build the runtime container image.
	$(DOCKER) build --tag $(IMAGE) .

docker-smoke: docker-build ## Run the image entrypoint smoke test.
	$(DOCKER) run --rm $(IMAGE) --version
