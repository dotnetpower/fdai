#!/usr/bin/env bash
#
# verify.sh - single-entry pre-commit gate runner for FDAI.
#
# Runs the CI-enforced quality gates in one shot so contributors do not have
# to remember five separate script names. Mirrors the gates already required
# by the coding-conventions and language instructions:
#
#   - ruff (Python lint)                        [core-only in --fast]
#   - check-english-only.sh (L0 English gate)
#   - check-punctuation.sh (ASCII typography)
#   - check-guids.sh (customer-agnostic GUIDs)
#   - check-translations.sh (foo.md <-> foo-ko.md SHA parity)
#   - check-catalog-parity.sh (L2 en/ko message catalogs)
#   - check-stewardship.sh (handover map: 15 agents, maintainer floor, no role fields)
#   - check-chaos-scenarios.sh (chaos-scenarios catalog + compiled symptom index)
#   - check-arb-readiness.py (ARB artifact, blocker, owner, evidence contract)
#   - pytest                                    [--full only]
#
# Usage:
#   scripts/verify.sh              # --fast (text + lint gates only)
#   scripts/verify.sh --fast       # same as default
#   scripts/verify.sh --full       # add pytest (whole suite)
#   scripts/verify.sh --full <path>  # pytest scoped to <path>
#
# Exit code: 0 on all-pass, 1 on any failure. Prints a summary at the end so
# the caller can see which gate needs attention without scrolling.

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

MODE="fast"
PYTEST_PATH=""
for arg in "$@"; do
    case "$arg" in
        --fast) MODE="fast" ;;
        --full) MODE="full" ;;
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

if command -v ruff >/dev/null 2>&1; then
    run_gate "ruff (src/fdai)" ruff check src/fdai
else
    echo "verify.sh: 'ruff' not found on PATH; skipping (activate the venv first)" >&2
    NAMES+=("ruff (src/fdai)")
    RESULTS+=("SKIP")
fi

run_gate "english-only" bash scripts/check-english-only.sh
run_gate "punctuation"  bash scripts/check-punctuation.sh
run_gate "guids"        bash scripts/check-guids.sh
run_gate "translations" bash scripts/check-translations.sh

if [[ -x scripts/check-catalog-parity.sh ]]; then
    run_gate "catalog-parity" bash scripts/check-catalog-parity.sh
fi

if [[ -f scripts/check-stewardship.sh ]]; then
    run_gate "stewardship" bash scripts/check-stewardship.sh
fi

if [[ -f scripts/check-chaos-scenarios.sh ]]; then
    run_gate "chaos-scenarios" bash scripts/check-chaos-scenarios.sh
fi

if [[ -f scripts/check-arb-readiness.py ]]; then
    run_gate "architecture-review" python3 scripts/check-arb-readiness.py
fi

# ---- full gates (opt-in) ----------------------------------------------------

if [[ "$MODE" == "full" ]]; then
    if command -v pytest >/dev/null 2>&1; then
        if [[ -n "$PYTEST_PATH" ]]; then
            run_gate "pytest ($PYTEST_PATH)" pytest -q --no-cov "$PYTEST_PATH"
        else
            run_gate "pytest (all)" pytest -q --no-cov
        fi
    else
        echo "verify.sh: 'pytest' not found; activate .venv before --full" >&2
        NAMES+=("pytest")
        RESULTS+=("SKIP")
        overall=1
    fi
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
