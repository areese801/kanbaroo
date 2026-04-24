.PHONY: help build publish tag lint format test clean sync web-build web-dev web-test

# Kanbaroo is a uv workspace monorepo. `uv build --all-packages`
# builds every workspace member (kanbaroo-core, kanbaroo-api,
# kanbaroo-cli, kanbaroo-tui, kanbaroo-mcp, kanbaroo-web) plus the
# top-level `kanbaroo` meta-package into dist/.
#
# `make publish` runs `web-build` first so the release wheel carries
# fresh JS/CSS. `make build` skips the frontend step so dev iteration
# stays fast; use `make web-build` explicitly when you need the SPA.
#
# Publishing uses `uv publish`, which reads UV_PUBLISH_TOKEN from
# the environment (see set_creds.sh for the canonical source).

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

sync: ## Sync the workspace venv with all packages and dev deps
	uv sync --all-packages --dev

build: clean ## Build wheels and sdists for every workspace member into dist/
	uv build --all-packages --out-dir dist/

publish: web-build build ## Rebuild the SPA, build wheels, upload to PyPI, and push a v<version> git tag
	. ./set_creds.sh && uv publish dist/*
	$(MAKE) tag

tag: ## Create and push a v<version> git tag from the root pyproject.toml version
	@VERSION=$$(grep '^version' pyproject.toml | head -1 | cut -d'"' -f2); \
	 if git rev-parse "v$$VERSION" >/dev/null 2>&1; then \
	   echo "Tag v$$VERSION already exists - skipping."; \
	 else \
	   git tag -a "v$$VERSION" -m "Release v$$VERSION" && \
	   git push origin "v$$VERSION" && \
	   echo "Tagged and pushed v$$VERSION."; \
	 fi

lint: ## Run ruff check across the workspace
	uv run ruff check .

format: ## Run ruff format across the workspace
	uv run ruff format .

test: ## Run the full pytest suite
	uv run pytest

clean: ## Remove build artifacts
	rm -rf dist/ build/
	find packages -type d -name '*.egg-info' -exec rm -rf {} +

web-build: ## Build the kanbaroo-web frontend into packages/kanbaroo-web/src/kanbaroo_web/dist/
	cd packages/kanbaroo-web/frontend && npm ci && npm run build

web-dev: ## Run the Vite dev server for the kanbaroo-web frontend (proxies /api and /api/v1/events to :8080)
	cd packages/kanbaroo-web/frontend && npm run dev

web-test: ## Run the kanbaroo-web frontend test suite (vitest, single-shot)
	cd packages/kanbaroo-web/frontend && npm test -- --run
