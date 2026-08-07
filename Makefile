# Convenience targets:
#   `dev-*`   - local dev stack (pgvector + Redpanda), see `infra/local/`.
#   `lint`, `format`, `test`, `gates`, `check` - local mirror of the CI jobs
#     in `.github/workflows/ci.yml`. `check` runs everything CI runs so a
#     contributor can reproduce a failing PR locally in one command.
# Real deployment lives under `infra/` (Terraform); see the roadmap.

.PHONY: dev-up dev-down dev-logs dev-nuke help \
	lint format test test-changed service-test service-test-all operator gates check validation-status validation-run \
	validation-all roadmap-verification-sync roadmap-verification-status \
	roadmap-verification-report roadmap-verification-apply pre-commit-install hooks-install \
        azd-up genesis-up

help: ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev-up: ## start pgvector + Redpanda locally (waits for healthchecks)
	@scripts/deployment/local/dev-up.sh

dev-down: ## stop the local stack (volumes preserved)
	@scripts/deployment/local/dev-down.sh

dev-logs: ## tail postgres + redpanda logs (optional: SERVICE=postgres)
	@scripts/deployment/local/dev-logs.sh $(SERVICE)

dev-nuke: ## stop the stack AND drop its volumes (fresh state next `dev-up`)
	@docker compose -f infra/local/docker-compose.yml down -v

azd-up: ## turnkey provision preview (azd + Terraform); FDAI_AZD_CONFIRM=1 to apply
	@scripts/deployment/azure/azd-up.sh

genesis-up: ## Day-1 Genesis screen over 'terraform apply -json'; FDAI_GENESIS_CONFIRM=1 to apply
	@scripts/deployment/azure/genesis-up.sh

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
	bash scripts/quality/ci/run-python-tests.sh

test-changed: ## pytest paths affected by changes (optional: DIFF=origin/main...HEAD)
	@bash scripts/automation/tests-for-diff.sh --run $(DIFF)

service-test: ## run one service-owned suite (SERVICE=<service-id>)
	@test -n "$(SERVICE)" || (echo "SERVICE is required" >&2; exit 2)
	@uv run --extra dev python scripts/automation/run-service-tests.py "$(SERVICE)"

service-test-all: ## run all service-owned suites in canonical order
	@uv run --extra dev python scripts/automation/run-service-tests.py --all

operator: ## console + CLI tests, typecheck, build, and entry-bundle budget
	bash scripts/quality/ci/run-operator-surfaces.sh

gates: ## repo hygiene: punctuation / guids / translations / core-imports
	bash scripts/quality/repository/check-punctuation.sh
	bash scripts/quality/repository/check-guids.sh
	bash scripts/quality/localization/check-translations.sh
	bash scripts/quality/architecture/check-core-imports.sh

check: lint gates test operator ## full local CI parity

validation-status: ## show commits waiting for centralized integration validation
	@python3 scripts/automation/validation_queue.py status

validation-run: ## validate the pending batch with changed tests + fast gates
	@python3 scripts/automation/validation_queue.py run

validation-all: ## validate the pending batch with whole-repository gates
	@python3 scripts/automation/validation_queue.py run --all

roadmap-verification-sync: ## discover canonical roadmap documents and refresh queue freshness
	@python3 scripts/automation/roadmap_verification_cli.py sync

roadmap-verification-status: ## show durable roadmap verification job counts
	@python3 scripts/automation/roadmap_verification_cli.py status

roadmap-verification-report: ## audit one roadmap document without repository writes
	@python3 scripts/automation/roadmap_verification_worker.py

roadmap-verification-apply: ## apply one job in a clean campaign worktree and fast-forward it
	@python3 scripts/automation/roadmap_verification_worker.py --apply --integrate

pre-commit-install: hooks-install ## backwards-compatible alias for hooks-install
	@echo "pre-commit-install is configured through the tracked .githooks/pre-commit hook."

hooks-install: ## enable the shared tracked git hooks (git config core.hooksPath .githooks)
	git config core.hooksPath .githooks
	chmod +x .githooks/* scripts/automation/git-auto-pull.sh 2>/dev/null || true
	@echo "pre-commit and pre-push hooks enabled (core.hooksPath=.githooks)."
