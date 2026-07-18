#!/usr/bin/env bash
#
# tests-for-diff.sh - map `git diff --name-only` -> matching pytest paths.
#
# Given a diff (working tree by default, or a commit range), this script
# prints the pytest paths that are relevant to the changed files. It maps
# src/fdai/<sub>/... -> tests/<sub>/... when tests/<sub>/ exists, and
# includes any test files that were themselves modified.
#
# Usage:
#   scripts/automation/tests-for-diff.sh                    # working tree vs HEAD
#   scripts/automation/tests-for-diff.sh HEAD~5..HEAD       # commit range
#   scripts/automation/tests-for-diff.sh --run              # also run pytest
#   scripts/automation/tests-for-diff.sh --run HEAD~1..HEAD # combined
#
# Notes:
#   - Deleted files are skipped (nothing to test).
#   - Non-python changes are ignored (docs / infra / configs are covered
#     by the fast text gates in scripts/verify.sh).
#   - Output is deduplicated and lexicographically sorted.
#   - Exit 0 with an empty stdout when there is nothing python-shaped to
#     test.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

run_pytest=0
diff_arg=""
for arg in "$@"; do
    case "$arg" in
        --run) run_pytest=1 ;;
        -h|--help)
            sed -n '2,22p' "$0"
            exit 0
            ;;
        *)
            if [[ -n "$diff_arg" ]]; then
                echo "tests-for-diff.sh: only one diff range accepted" >&2
                exit 2
            fi
            diff_arg="$arg"
            ;;
    esac
done

if [[ -z "$diff_arg" ]]; then
    changed=$(git diff --name-only --diff-filter=d HEAD)
    # Include staged-but-uncommitted files.
    staged=$(git diff --cached --name-only --diff-filter=d)
    changed=$(printf '%s\n%s\n' "$changed" "$staged" | sort -u)
else
    changed=$(git diff --name-only --diff-filter=d "$diff_arg")
fi

declare -A seen=()
tests=()

add_test() {
    local path="$1"
    [[ -z "$path" ]] && return
    [[ -e "$path" ]] || return
    if [[ -z "${seen[$path]:-}" ]]; then
        seen[$path]=1
        tests+=("$path")
    fi
}

while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    [[ "$file" == *.py ]] || continue

    # Test file changed directly - include it as-is.
    if [[ "$file" == tests/* ]]; then
        add_test "$file"
        continue
    fi

    # Source file - map to the mirrored test path.
    #   src/fdai/core/<sub>/*.py            -> tests/core/<sub>/
    #   src/fdai/agents/*.py                -> tests/agents/
    #   src/fdai/delivery/<sub>/*.py        -> tests/delivery/<sub>/
    #   src/fdai/shared/<sub>/*.py          -> tests/shared/<sub>/
    #   src/fdai/rule_catalog/*.py          -> tests/rule_catalog/
    #   src/fdai/composition/*.py           -> tests/composition/
    if [[ "$file" == src/fdai/* ]]; then
        rel="${file#src/fdai/}"           # e.g. core/risk_gate/foo.py
        first="${rel%%/*}"                # core
        rest="${rel#*/}"                  # risk_gate/foo.py
        if [[ "$rest" == "$rel" ]]; then
            # Flat file directly under src/fdai/
            candidate="tests"
        else
            case "$first" in
                core|delivery|shared)
                    sub="${rest%%/*}"     # risk_gate
                    if [[ "$sub" == "$rest" ]]; then
                        candidate="tests/${first}"
                    else
                        candidate="tests/${first}/${sub}"
                    fi
                    ;;
                agents|rule_catalog|composition)
                    candidate="tests/${first}"
                    ;;
                *)
                    candidate="tests/${first}"
                    ;;
            esac
        fi
        add_test "$candidate"
    fi
done <<< "$changed"

if [[ ${#tests[@]} -eq 0 ]]; then
    exit 0
fi

# Sort and dedupe.
mapfile -t tests < <(printf '%s\n' "${tests[@]}" | sort -u)

printf '%s\n' "${tests[@]}"

if [[ $run_pytest -eq 1 ]]; then
    if ! command -v pytest >/dev/null 2>&1; then
        echo "tests-for-diff.sh: pytest not on PATH; activate .venv first" >&2
        exit 2
    fi
    echo "--- running pytest on the paths above ---" >&2
    exec pytest -q --no-cov "${tests[@]}"
fi
