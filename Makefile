# Convenience targets:
#   `dev-*`   - local dev stack (pgvector + Redpanda), see `infra/local/`.
#   `lint`, `format`, `test`, `gates`, `check` - local mirror of the CI jobs
#     in `.github/workflows/ci.yml`. `check` runs everything CI runs so a
#     contributor can reproduce a failing PR locally in one command.
# Real deployment lives under `infra/` (Terraform); see the roadmap.

.PHONY: dev-up dev-down dev-logs dev-nuke help \
        lint format test gates check pre-commit-install hooks-install \
        azd-up genesis-up

help: ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev-up: ## start pgvector + Redpanda locally (waits for healthchecks)
	@scripts/dev-up.sh

dev-down: ## stop the local stack (volumes preserved)
	@scripts/dev-down.sh

dev-logs: ## tail postgres + redpanda logs (optional: SERVICE=postgres)
	@scripts/dev-logs.sh $(SERVICE)

dev-nuke: ## stop the stack AND drop its volumes (fresh state next `dev-up`)
	@docker compose -f infra/local/docker-compose.yml down -v

azd-up: ## turnkey provision preview (azd + Terraform); FDAI_AZD_CONFIRM=1 to apply
	@scripts/azd-up.sh

genesis-up: ## Day-1 Genesis screen over 'terraform apply -json'; FDAI_GENESIS_CONFIRM=1 to apply
	@scripts/genesis-up.sh

# ---------------------------------------------------------------------------
# CI-parity targets. Each mirrors one job in .github/workflows/ci.yml so a
# contributor can reproduce the merge gate without pushing.
# ---------------------------------------------------------------------------

lint: ## ruff check + ruff format --check + mypy --strict
	uv run ruff format --check src tests
	uv run ruff check src tests
	uv run mypy

format: ## apply ruff format + ruff --fix (mutates files)
	uv run ruff format src tests
	uv run ruff check --fix src tests

test: ## pytest with safety-core branch coverage (--cov-fail-under=90 matches CI)
	uv run pytest -q --cov=src/fdai/core/tiers/t0_deterministic --cov=src/fdai/core/risk_gate --cov-branch --cov-report=term-missing --cov-fail-under=90

gates: ## repo hygiene: punctuation / guids / translations / core-imports
	bash scripts/check-punctuation.sh
	bash scripts/check-guids.sh
	bash scripts/check-translations.sh
	bash scripts/check-core-imports.sh

check: lint gates test ## full local CI parity: lint + gates + test

pre-commit-install: hooks-install ## backwards-compatible alias for hooks-install
	@echo "pre-commit-install is configured through the tracked .githooks/pre-commit hook."

hooks-install: ## enable the shared tracked git hooks (git config core.hooksPath .githooks)
	git config core.hooksPath .githooks
	chmod +x .githooks/* scripts/git-auto-pull.sh 2>/dev/null || true
	@echo "pre-commit and pre-push hooks enabled (core.hooksPath=.githooks)."
