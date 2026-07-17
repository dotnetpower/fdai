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
#   - mypy (strict static types)
#   - pytest                                    [--full only]
#
# Usage:
#   scripts/verify.sh              # --fast (text + lint + strict type gates)
#   scripts/verify.sh --fast       # same as default
#   scripts/verify.sh --full       # add pytest (whole suite)
#   scripts/verify.sh --full <path>  # pytest scoped to <path>
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

# User-facing docs pinned to roadmap reference docs via derives_from[].sha.
# Fails when a roadmap source moved and the user-facing doc has not been
# reviewed + re-pinned (scripts/refresh-derived-sha.py). Opt-in: only docs
# that declare derives_from are checked.
if [[ -f scripts/check-derived-sources.py ]]; then
    run_gate "derived-sources" python3 scripts/check-derived-sources.py
fi

# Framework-surface integrity: offline signature + content verification.
# Upstream: advisory (edits are legitimate; re-sign before release, rc 0).
# Fork: hard fail on any edit/add under the signed surface (rc 1). Skipped
# gracefully until the signed manifest exists.
if [[ -f scripts/check-integrity.sh && -f security/integrity/manifest.json.sig ]]; then
    run_gate "framework-integrity" bash scripts/check-integrity.sh
fi

# ---- full gates (opt-in) ----------------------------------------------------

if [[ "$MODE" == "full" ]]; then
    if command -v uv >/dev/null 2>&1; then
        pytest_cmd=(uv run pytest)
    elif command -v pytest >/dev/null 2>&1; then
        pytest_cmd=(pytest)
    else
        pytest_cmd=()
    fi
    if [[ ${#pytest_cmd[@]} -gt 0 ]]; then
        if [[ -n "$PYTEST_PATH" ]]; then
            run_gate "pytest ($PYTEST_PATH)" "${pytest_cmd[@]}" -q --no-cov "$PYTEST_PATH"
        else
            if [[ -n "${FDAI_DATABASE_URL:-}" ]]; then
                run_gate "pytest (all)" "${pytest_cmd[@]}" -q --no-cov
            else
                printf '%s\n' "verify.sh: FDAI_DATABASE_URL unset; skipping integration marker"
                run_gate "pytest (no integration)" "${pytest_cmd[@]}" -q --no-cov -m "not integration"
            fi
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
