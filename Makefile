.DEFAULT_GOAL := help

UV ?= uv
DOCKER ?= docker
IMAGE_NAME ?= dbtalk
IMAGE_TAG ?= latest
IMAGE := $(IMAGE_NAME):$(IMAGE_TAG)
CHECK_FIX := $(filter 1 true yes,$(fix) $(FIX))
RUFF_CHECK_ARGS :=
RUFF_FORMAT_ARGS := --check

ifneq ($(CHECK_FIX),)
RUFF_CHECK_ARGS := --fix
RUFF_FORMAT_ARGS :=
endif

.PHONY: help sync check test package release docker-build docker-smoke

help: ## Show available targets.
	@echo "Usage: make <target> [IMAGE_NAME=registry/dbtalk] [IMAGE_TAG=1.0.0]"
	@echo ""
	@echo "Targets:"
	@echo "  sync          Install locked development dependencies"
	@echo "  check         Run Ruff and Mypy quality checks (fix=1 enables fixes)"
	@echo "  test          Run Pytest with branch coverage enforcement"
	@echo "  package       Build source and wheel distributions"
	@echo "  release       Preflight plugins, install dbtalk, then apply plugins"
	@echo "  docker-build  Build the runtime container image"
	@echo "  docker-smoke  Run the image entrypoint with --version"

sync: ## Install all locked dependency groups.
	$(UV) sync --all-groups --locked

check: ## Run Ruff and Mypy checks without tests; use fix=1 to fix Ruff issues.
	$(UV) run ruff check . $(RUFF_CHECK_ARGS)
	$(UV) run ruff format $(RUFF_FORMAT_ARGS) .
	$(UV) run mypy src tests

test: ## Run tests with branch coverage enforcement.
	$(UV) run pytest
	python scripts/test_release.py

package: ## Build source and wheel distributions.
	$(UV) build

release: ## Preflight plugins, install dbtalk, then apply plugins.
	python scripts/release.py plugin check
	pip install -e .
	python scripts/release.py plugin apply

docker-build: ## Build the runtime container image.
	$(DOCKER) build --tag $(IMAGE) .

docker-smoke: docker-build ## Run the image entrypoint smoke test.
	$(DOCKER) run --rm $(IMAGE) --version
