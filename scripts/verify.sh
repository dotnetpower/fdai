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
#   scripts/verify.sh --full <path>  # add pytest scoped to <path>
#   scripts/verify.sh --all          # whole pytest + operator suite (explicit)
#
# Exit code: 0 on all-pass, 1 on any failure. Prints a summary at the end so
# the caller can see which gate needs attention without scrolling.

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root" || exit 1

MODE="fast"
PYTEST_PATH=""
for arg in "$@"; do
    case "$arg" in
        --fast) MODE="fast" ;;
        --full) MODE="full" ;;
        --all) MODE="all" ;;
        -h|--help)
            sed -n '2,25p' "$0"
            exit 0
            ;;
        *)
            if [[ -z "$PYTEST_PATH" ]]; then
                PYTEST_PATH="$arg"
            else
                echo "verify.sh: unknown extra argument '$arg'" >&2
                exit 2
            fi
            ;;
    esac
done

if [[ "$MODE" == "full" && -z "$PYTEST_PATH" ]]; then
    echo "verify.sh: --full requires a pytest path; use make test-changed during development or --all for an explicit whole-suite run" >&2
    exit 2
fi
if [[ "$MODE" == "all" && -n "$PYTEST_PATH" ]]; then
    echo "verify.sh: --all does not accept a pytest path; use --full <path> for focused verification" >&2
    exit 2
fi

declare -a NAMES=()
declare -a RESULTS=()
overall=0

run_gate() {
    local name="$1"
    shift
    printf '\n== %s ==\n' "$name"
    if "$@"; then
        NAMES+=("$name")
        RESULTS+=("PASS")
    else
        NAMES+=("$name")
        RESULTS+=("FAIL")
        overall=1
    fi
}

# ---- fast gates (always) ----------------------------------------------------

if command -v uv >/dev/null 2>&1; then
    run_gate "ruff format (src tests)" uv run ruff format --check src tests
    run_gate "ruff lint (src tests)" uv run ruff check src tests
elif command -v ruff >/dev/null 2>&1; then
    run_gate "ruff format (src tests)" ruff format --check src tests
    run_gate "ruff lint (src tests)" ruff check src tests
else
    echo "verify.sh: 'ruff' not found on PATH; skipping (activate the venv first)" >&2
    NAMES+=("ruff format (src tests)" "ruff lint (src tests)")
    RESULTS+=("SKIP" "SKIP")
fi

if command -v uv >/dev/null 2>&1; then
    run_gate "mypy (strict)" uv run mypy
else
    echo "verify.sh: 'uv' not found; install uv before verification" >&2
    NAMES+=("mypy (strict)")
    RESULTS+=("FAIL")
    overall=1
fi

run_gate "ci-contracts" python3 scripts/quality/ci/check-ci-contracts.py
run_gate "issue-lifecycle" python3 scripts/quality/repository/check-issue-lifecycle.py
run_gate "design-routes" python3 scripts/quality/architecture/check-design-routes.py
run_gate "design-doc-impact" python3 scripts/quality/architecture/check-design-doc-impact.py
run_gate "fork-runtime-independence" python3 scripts/quality/architecture/check-fork-runtime-independence.py
run_gate "document-size" python3 scripts/quality/architecture/check-document-size.py
run_gate "display-terminology" python3 scripts/quality/documentation/check-display-terminology.py

run_gate "punctuation"  bash scripts/quality/repository/check-punctuation.sh
run_gate "readable-hangul" python3 scripts/quality/localization/check-readable-hangul.py
run_gate "guids"        bash scripts/quality/repository/check-guids.sh
run_gate "translations" bash scripts/quality/localization/check-translations.sh

run_gate "catalog-parity" bash scripts/quality/localization/check-catalog-parity.sh
run_gate "stewardship" bash scripts/governance/check-stewardship.sh
run_gate "chaos-scenarios" bash scripts/catalog/check-chaos-scenarios.sh
run_gate "architecture-review" python3 scripts/governance/check-arb-readiness.py

# User-facing docs pinned to roadmap reference docs via derives_from[].sha.
# Fails when a roadmap source moved and the user-facing doc has not been
# reviewed + re-pinned (scripts/quality/localization/refresh-derived-sha.py). Opt-in: only docs
# that declare derives_from are checked.
run_gate "derived-sources" python3 scripts/quality/localization/check-derived-sources.py

# Framework-surface integrity: offline signature + content verification.
# Upstream: advisory (edits are legitimate; re-sign before release, rc 0).
# Fork: hard fail on any edit/add under the signed surface (rc 1). Skipped
# loudly when any signed artifact is missing.
run_gate "framework-integrity" bash scripts/integrity/check-integrity.sh

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
