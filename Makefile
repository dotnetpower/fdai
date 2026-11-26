# Convenience targets (100% Pure-Rust workspace & local dev stack):
#   `dev-*`            - local dev stack (pgvector + Redpanda), see `infra/local/`.
#   `rust-fullstack-*` - Pure-Rust Axum services + Console v4, see `deploy_rs/`.
#   `lint`, `format`, `test`, `gates`, `xtask`, `check` - Pure-Rust validation entry points.

.PHONY: dev-up dev-down dev-logs dev-nuke help rust-fullstack-up rust-fullstack-down \
	console-v4-up lint format test xtask check-migrations gates check \
	pre-commit-install hooks-install azd-up genesis-up

help: ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev-up: ## start pgvector + Redpanda locally (waits for healthchecks)
	@scripts/deployment/local/dev-up.sh

dev-down: ## stop the local stack (volumes preserved)
	@scripts/deployment/local/dev-down.sh

dev-logs: ## tail postgres + redpanda logs (optional: SERVICE=postgres)
	@scripts/deployment/local/dev-logs.sh $(SERVICE)

dev-nuke: ## stop the stack AND drop its volumes (fresh state next `dev-up`)
	@docker compose -f infra/local/docker-compose.yml down -v

rust-fullstack-up: ## build and start all 8 Pure-Rust Axum services + Hubs
	@bash deploy_rs/start-fullstack-rust.sh

rust-fullstack-down: ## stop the local Pure-Rust fullstack services
	@bash deploy_rs/stop-fullstack-rust.sh

console-v4-up: ## run Pure-Rust FDAI Console v4 server on 127.0.0.1:5290
	cargo run --offline -p fdai-console-v4 -- --host 127.0.0.1 --port 5290

azd-up: ## deploy public dev Core from the active az login; asks for region
	@scripts/deployment/azure/azd-up.sh

genesis-up: ## explain the retired Terraform-stream prototype and canonical fdaictl path
	@scripts/deployment/azure/genesis-up.sh

# ---------------------------------------------------------------------------
# Pure-Rust workspace quality & verification gates (zero Python dependency)
# ---------------------------------------------------------------------------

lint: ## cargo check across the full Pure-Rust workspace
	cargo check --workspace --offline

format: ## format Rust sources across the workspace
	cargo fmt --all

test: ## run all Pure-Rust workspace unit and integration tests
	cargo test --workspace --offline

xtask: ## run Zero-Python, Hexagonal Core, Zero-Attribution & hollow-fn ratchet gates
	cargo run --offline -p fdai-xtask -- verify

check-migrations: ## verify all 259 SQL migration files and execution order manifest
	cargo run --offline -p fdai-xtask -- check-migrations

gates: xtask check-migrations ## run all Pure-Rust architectural, Zero-Python, hygiene, and SQL gates
	cargo run --offline -p fdai-xtask -- check-hygiene

check: lint gates test ## run full local Pure-Rust workspace verification

pre-commit-install: hooks-install ## backwards-compatible alias for hooks-install
	@echo "pre-commit-install is configured through the tracked .githooks/pre-commit hook."

hooks-install: ## enable the shared tracked git hooks (git config core.hooksPath .githooks)
	git config core.hooksPath .githooks
	chmod +x .githooks/* scripts/automation/git-auto-pull.sh 2>/dev/null || true
	@echo "Pure-Rust pre-commit and pre-push hooks enabled (core.hooksPath=.githooks)."
