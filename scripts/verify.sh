#!/usr/bin/env bash
#
# verify.sh - single-entry pre-commit gate runner for FDAI.
#
# Runs the CI-enforced quality gates in one shot so contributors do not have
# to remember five separate script names. Mirrors the gates already required
# by the coding-conventions and language instructions:
#
#   - ruff format + lint (Python source/tests)
#   - check-punctuation.sh (ASCII typography)
#   - check-guids.sh (customer-agnostic GUIDs)
#   - check-translations.sh (foo.md <-> foo-ko.md SHA parity)
#   - check-catalog-parity.sh (L2 en/ko message catalogs)
#   - check-stewardship.sh (handover map: 15 agents, maintainer floor, no role fields)
#   - check-chaos-scenarios.sh (chaos-scenarios catalog + compiled symptom index)
#   - check-arb-readiness.py (ARB artifact, blocker, owner, evidence contract)
#   - clean-checkout / Docker build-context contracts
#   - mypy (strict static types)
#   - pytest scoped to one path                 [--full <path> only]
#   - pytest + safety-core coverage             [--all only]
#   - console + CLI tests/typecheck/build       [--all only]
#
# Usage:
#   scripts/verify.sh              # --fast (text + lint + strict type gates)
#   scripts/verify.sh --fast       # same as default
#   scripts/verify.sh --fast --diff <range>  # skip unrelated fast gates
#   scripts/verify.sh --full <path>  # add pytest scoped to <path>
#   scripts/verify.sh --all          # whole pytest + operator suite (explicit)
#
# Exit code: 0 on all-pass, 1 on any failure. Prints a summary at the end so
# the caller can see which gate needs attention without scrolling.

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root" || exit 1
export PYTHONPATH="$repo_root/services/core-control-plane/src:$repo_root/packages/service-contracts/src${PYTHONPATH:+:$PYTHONPATH}"

MODE="fast"
PYTEST_PATH=""
DIFF_RANGE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --fast) MODE="fast" ;;
        --full) MODE="full" ;;
        --all) MODE="all" ;;
        --diff)
            shift
            if [[ $# -eq 0 || -z "$1" ]]; then
                echo "verify.sh: --diff requires a git revision range" >&2
                exit 2
            fi
            DIFF_RANGE="$1"
            ;;
        -h|--help)
            sed -n '2,25p' "$0"
            exit 0
            ;;
        *)
            if [[ -z "$PYTEST_PATH" ]]; then
                PYTEST_PATH="$1"
            else
                echo "verify.sh: unknown extra argument '$1'" >&2
                exit 2
            fi
            ;;
    esac
    shift
done

if [[ "$MODE" == "full" && -z "$PYTEST_PATH" ]]; then
    echo "verify.sh: --full requires a pytest path; use make test-changed during development or --all for an explicit whole-suite run" >&2
    exit 2
fi
if [[ "$MODE" == "all" && -n "$PYTEST_PATH" ]]; then
    echo "verify.sh: --all does not accept a pytest path; use --full <path> for focused verification" >&2
    exit 2
fi
if [[ "$MODE" != "fast" && -n "$DIFF_RANGE" ]]; then
    echo "verify.sh: --diff is supported only with --fast" >&2
    exit 2
fi
if [[ -n "$DIFF_RANGE" && -n "$PYTEST_PATH" ]]; then
    echo "verify.sh: --fast --diff does not accept a pytest path" >&2
    exit 2
fi

CHANGED_FILES=""
if [[ -n "$DIFF_RANGE" ]]; then
    if ! CHANGED_FILES=$(git diff --name-only --no-renames --diff-filter=ACMRTD "$DIFF_RANGE"); then
        echo "verify.sh: unable to resolve diff range '$DIFF_RANGE'" >&2
        exit 2
    fi
fi

declare -a NAMES=()
declare -a RESULTS=()
overall=0

run_gate() {
    local name="$1"
    shift
    printf '\n== %s ==\n' "$name"
    local cache_file=""
    if [[ -n "${FDAI_VERIFY_CACHE_DIR:-}" && -n "$DIFF_RANGE" && "$MODE" == "fast" ]]; then
        local cache_key
        cache_key=$(printf '%s\n%s\n%s\n%s\n' "$(git rev-parse HEAD)" "$DIFF_RANGE" "$name" "${FDAI_VERIFY_CONTEXT_DIGEST:-}" | sha256sum | cut -d' ' -f1)
        cache_file="$FDAI_VERIFY_CACHE_DIR/$cache_key.pass"
        if [[ -f "$cache_file" ]]; then
            NAMES+=("$name")
            RESULTS+=("CACHED")
            printf 'validation cache: PASS\n'
            return 0
        fi
    fi
    local started_ms
    started_ms=$(date +%s%3N)
    if "$@"; then
        NAMES+=("$name")
        RESULTS+=("PASS")
        if [[ -n "$cache_file" ]]; then
            mkdir -p "$(dirname "$cache_file")"
            : > "$cache_file"
        fi
    else
        NAMES+=("$name")
        RESULTS+=("FAIL")
        overall=1
    fi
    local duration_ms=$(( $(date +%s%3N) - started_ms ))
    printf 'gate duration: %d ms\n' "$duration_ms"
}

changed_matches() {
    local pattern="$1"
    [[ -z "$DIFF_RANGE" ]] ||
        grep -qx 'scripts/verify.sh' <<< "$CHANGED_FILES" ||
        grep -Eq "$pattern" <<< "$CHANGED_FILES"
}

run_gate_scoped() {
    local name="$1"
    local pattern="$2"
    shift 2
    if changed_matches "$pattern"; then
        run_gate "$name" "$@"
    else
        printf '\n== %s ==\nscoped diff: SKIP\n' "$name"
        NAMES+=("$name")
        RESULTS+=("SKIP")
    fi
}

# ---- fast gates (always) ----------------------------------------------------

if command -v uv >/dev/null 2>&1; then
    run_gate_scoped "ruff format (services packages tests extensions)" '(^|/).*\.py$|^pyproject\.toml$|^uv\.lock$' uv run ruff format --check services packages tests extensions/code-assurance
    run_gate_scoped "ruff lint (services packages tests extensions)" '(^|/).*\.py$|^pyproject\.toml$|^uv\.lock$' uv run ruff check services packages tests extensions/code-assurance
elif command -v ruff >/dev/null 2>&1; then
    run_gate "ruff format (services packages tests extensions)" ruff format --check services packages tests extensions/code-assurance
    run_gate "ruff lint (services packages tests extensions)" ruff check services packages tests extensions/code-assurance
else
    echo "verify.sh: 'ruff' not found on PATH; skipping (activate the venv first)" >&2
    NAMES+=("ruff format (src tests extensions)" "ruff lint (src tests extensions)")
    RESULTS+=("SKIP" "SKIP")
fi

if command -v uv >/dev/null 2>&1; then
    run_gate_scoped "mypy (strict)" '(^|/).*\.py$|^pyproject\.toml$|^uv\.lock$' uv run mypy
else
    echo "verify.sh: 'uv' not found; install uv before verification" >&2
    NAMES+=("mypy (strict)")
    RESULTS+=("FAIL")
    overall=1
fi

run_gate_scoped "ci-contracts" '^(\.github/workflows/|Dockerfile$|\.dockerignore$|resolved-models.*\.json$|scripts/quality/ci/|services/core-control-plane/tests/persistence/|services/core-control-plane/src/fdai/)' python3 scripts/quality/ci/check-ci-contracts.py
run_gate_scoped "issue-lifecycle" '^(\.github/ISSUE_TEMPLATE/|\.github/workflows/issue-lifecycle\.yml$|\.github/copilot-instructions\.md$|CONTRIBUTING\.md$|scripts/quality/repository/check-issue-lifecycle\.py$)' python3 scripts/quality/repository/check-issue-lifecycle.py
run_gate_scoped "design-routes" '^(\.github/instructions/|scripts/lib/design-routes\.json$|scripts/quality/architecture/check-design-routes\.py$|docs/)' python3 scripts/quality/architecture/check-design-routes.py
run_gate_scoped "constitution" '^(\.github/|config/constitution-traceability\.json$|docs/roadmap/|scripts/quality/architecture/check-constitution\.py$)' python3 scripts/quality/architecture/check-constitution.py
design_doc_impact=(python3 scripts/quality/architecture/check-design-doc-impact.py)
if [[ -n "$DIFF_RANGE" ]]; then
    design_doc_impact+=("$DIFF_RANGE")
fi
run_gate "design-doc-impact" "${design_doc_impact[@]}"
run_gate_scoped "fork-runtime-independence" '^(src/|config/|infra/|scripts/quality/architecture/check-fork-runtime-independence\.py$)' python3 scripts/quality/architecture/check-fork-runtime-independence.py
run_gate_scoped "evaluation-boundaries" '^(evaluation-sdk/|src/|tests/|pyproject\.toml$|scripts/quality/architecture/check-evaluation-boundaries\.py$)' python3 scripts/quality/architecture/check-evaluation-boundaries.py
run_gate_scoped "independent-services" '^(services/|packages/service-contracts/|tests/integration/|config/independent-services\.json$|scripts/quality/architecture/check-independent-services\.py$)' uv run python scripts/quality/architecture/check-independent-services.py
run_gate_scoped "chat-semantic-routing" '^(services/operator-service/|console/|tests/integration/|scripts/quality/architecture/check-chat-semantic-routing\.py$)' python3 scripts/quality/architecture/check-chat-semantic-routing.py
run_gate_scoped "ontology-query-coverage" '^(config/ontology-query-competency\.json|packages/service-contracts/src/fdai_service_contracts/ontology_query\.py|rule-catalog/vocabulary/|services/core-control-plane/src/fdai/core/(conversation|ontology_platform)/|services/core-control-plane/src/fdai/rule_catalog/schema/|scripts/quality/architecture/check-ontology-query-coverage\.py$)' uv run python scripts/quality/architecture/check-ontology-query-coverage.py
run_gate_scoped "boundary-docstrings" '^(src/|scripts/quality/architecture/(check-boundary-docstrings\.py|\.boundary-docstring-scopes)$)' python3 scripts/quality/architecture/check-boundary-docstrings.py
run_gate_scoped "document-size" '^(docs/roadmap/|scripts/quality/architecture/check-document-size\.py$)' python3 scripts/quality/architecture/check-document-size.py
run_gate_scoped "display-terminology" '^(README|docs/|rule-catalog/|console/|cli/|scripts/quality/documentation/check-display-terminology\.py$)' python3 scripts/quality/documentation/check-display-terminology.py

run_gate "punctuation"  bash scripts/quality/repository/check-punctuation.sh
run_gate "readable-hangul" python3 scripts/quality/localization/check-readable-hangul.py
run_gate "guids"        bash scripts/quality/repository/check-guids.sh
run_gate_scoped "translations" '^(README(-ko)?\.md$|docs/.*\.md$|scripts/quality/localization/check-translations\.sh$)' bash scripts/quality/localization/check-translations.sh

run_gate_scoped "catalog-parity" '^(console|cli|src)/.*messages\.(en|ko)\.json$|^scripts/quality/localization/check-catalog-parity\.sh$' bash scripts/quality/localization/check-catalog-parity.sh
run_gate_scoped "stewardship" '^(config/agent-stewardship\.yaml$|services/core-control-plane/src/fdai/agents/_framework/pantheon\.py$|scripts/governance/check-stewardship\.sh$)' bash scripts/governance/check-stewardship.sh
run_gate_scoped "chaos-scenarios" '^(rule-catalog/chaos-scenarios/|docs/user-guide/sre/scenario-validation-inventory|scripts/catalog/)' bash scripts/catalog/check-chaos-scenarios.sh
run_gate_scoped "architecture-review" '^(config/architecture-review\.yaml$|scripts/governance/check-arb-readiness\.py$)' python3 scripts/governance/check-arb-readiness.py

# User-facing docs pinned to roadmap reference docs via derives_from[].sha.
# Fails when a roadmap source moved and the user-facing doc has not been
# reviewed + re-pinned (scripts/quality/localization/refresh-derived-sha.py). Opt-in: only docs
# that declare derives_from are checked.
run_gate_scoped "derived-sources" '^(README(-ko)?\.md$|docs/|scripts/quality/localization/check-derived-sources\.py$)' python3 scripts/quality/localization/check-derived-sources.py

# Framework-surface integrity: offline signature + content verification.
# Upstream: advisory (edits are legitimate; re-sign before release, rc 0).
# Fork: hard fail on any edit/add under the signed surface (rc 1). Skipped
# loudly when any signed artifact is missing.
run_gate_scoped "framework-integrity" '^(services/core-control-plane/src/fdai/(core/|agents/|composition|shared/(contracts|providers)/)|rule-catalog/schema/|\.github/instructions/|security/integrity/|scripts/integrity/)' bash scripts/integrity/check-integrity.sh

# ---- pytest and whole-repository gates (opt-in) -----------------------------

if [[ "$MODE" == "full" ]]; then
    run_gate "pytest ($PYTEST_PATH)" uv run pytest -q --no-cov "$PYTEST_PATH"
elif [[ "$MODE" == "all" ]]; then
    run_gate "pytest + coverage" bash scripts/quality/ci/run-python-tests.sh
    run_gate "operator surfaces" bash scripts/quality/ci/run-operator-surfaces.sh
fi

# ---- summary ---------------------------------------------------------------

printf '\n== summary ==\n'
for i in "${!NAMES[@]}"; do
    printf '  %-24s %s\n' "${NAMES[$i]}" "${RESULTS[$i]}"
done

if [[ $overall -eq 0 ]]; then
    printf '\nverify.sh: all gates green\n'
else
    printf '\nverify.sh: at least one gate failed\n' >&2
fi

exit "$overall"
