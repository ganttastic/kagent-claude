.PHONY: help install test lint format build push run run-hitl run-custom run-server clean

PACKAGE_DIR := python/packages/kagent-claude
IMAGE       ?= ghcr.io/ganttastic/kagent-claude
TAG         ?= latest
PORT        ?= 8080

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ── Development ──────────────────────────────────────────────

install: ## Install the package (editable + dev deps)
	pip install --pre -e "$(PACKAGE_DIR)[dev]"

test: ## Run the test suite
	pytest $(PACKAGE_DIR)/tests/ -v

lint: ## Run ruff linter
	ruff check $(PACKAGE_DIR)/src/ $(PACKAGE_DIR)/tests/ examples/

format: ## Auto-format with ruff
	ruff format $(PACKAGE_DIR)/src/ $(PACKAGE_DIR)/tests/ examples/
	ruff check --fix $(PACKAGE_DIR)/src/ $(PACKAGE_DIR)/tests/ examples/

# ── Run ──────────────────────────────────────────────────────

run-server: ## Run the golden image server locally (env-configured)
	KAGENT_URL=$${KAGENT_URL:-http://localhost:8083} \
	KAGENT_NAME=$${KAGENT_NAME:-claude-agent} \
	KAGENT_NAMESPACE=$${KAGENT_NAMESPACE:-default} \
	python -m kagent.claude.server

run: ## Run the basic example agent
	KAGENT_URL=$${KAGENT_URL:-http://localhost:8083} \
	KAGENT_NAME=$${KAGENT_NAME:-claude-agent} \
	KAGENT_NAMESPACE=$${KAGENT_NAMESPACE:-default} \
	python examples/basic.py

run-hitl: ## Run the HITL example agent
	KAGENT_URL=$${KAGENT_URL:-http://localhost:8083} \
	KAGENT_NAME=$${KAGENT_NAME:-hitl-agent} \
	KAGENT_NAMESPACE=$${KAGENT_NAMESPACE:-default} \
	python examples/hitl.py

run-custom: ## Run the custom config example agent
	KAGENT_URL=$${KAGENT_URL:-http://localhost:8083} \
	KAGENT_NAME=$${KAGENT_NAME:-custom-agent} \
	KAGENT_NAMESPACE=$${KAGENT_NAMESPACE:-default} \
	python examples/custom_config.py

# ── Docker (golden image) ───────────────────────────────────

build: ## Build the golden image (IMAGE=... TAG=...)
	docker build -t $(IMAGE):$(TAG) .

push: build ## Build and push the golden image
	docker push $(IMAGE):$(TAG)

# ── Cleanup ──────────────────────────────────────────────────

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
