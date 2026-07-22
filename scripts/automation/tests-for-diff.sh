#!/usr/bin/env bash
#
# tests-for-diff.sh - map `git diff --name-only` -> matching pytest paths.
#
# Given a diff (working tree by default, or a commit range), this script
# prints the pytest paths that are relevant to the changed files. It maps
# source and repository-data paths to their owning test directories, includes
# modified tests directly, and falls back to the full suite for global inputs.
#
# Usage:
#   scripts/automation/tests-for-diff.sh                    # working tree vs HEAD
#   scripts/automation/tests-for-diff.sh HEAD~5..HEAD       # commit range
#   scripts/automation/tests-for-diff.sh --run              # also run pytest
#   scripts/automation/tests-for-diff.sh --run HEAD~1..HEAD # combined
#
# Notes:
#   - Working-tree selection includes tracked, staged, and untracked files.
#   - Repository data with Python consumers maps to its owning test area.
#   - Global test and dependency configuration selects the full suite.
#   - Docs, console, CLI, and infrastructure changes without Python consumers
#     are covered by their dedicated gates instead of pytest.
#   - Output is deduplicated and lexicographically sorted.
#   - Exit 0 with an empty stdout when there is nothing python-shaped to
#     test.

set -euo pipefail

selector_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
    tracked=$(git diff --name-only --no-renames --diff-filter=ACMRTD HEAD)
    untracked=$(git ls-files --others --exclude-standard)
    changed=$(printf '%s\n%s\n' "$tracked" "$untracked" | sort -u)
else
    changed=$(git diff --name-only --no-renames --diff-filter=ACMRTD "$diff_arg")
fi

declare -A seen=()
tests=()
python_sources=()

add_test() {
    local path="$1"
    [[ -z "$path" ]] && return 0
    if [[ ! -e "$path" ]]; then
        path="tests"
    fi
    if [[ -z "${seen[$path]:-}" ]]; then
        seen[$path]=1
        tests+=("$path")
    fi
}

while IFS= read -r file; do
    [[ -z "$file" ]] && continue

    # These inputs can affect collection or every Python test. Selecting the
    # full suite is cheaper than silently missing a cross-cutting regression.
    case "$file" in
        .github/workflows/ci.yml|Dockerfile|Makefile|alembic.ini|pyproject.toml|uv.lock|tests/conftest.py)
            add_test "tests"
            continue
            ;;
        config/*|policies/*|rule-catalog/*)
            add_test "tests"
            continue
            ;;
        src/fdai/composition/*|src/fdai/rule_catalog/*|src/fdai/shared/contracts/*|src/fdai/shared/providers/*)
            add_test "tests"
            continue
            ;;
    esac

    if [[ ("$file" == tests/* || "$file" == src/*) && "$file" != *.py ]]; then
        add_test "tests"
        continue
    fi

    if [[ "$file" == *.py ]]; then
        case "$file" in
            src/fdai/*|delivery/*|scripts/*|tools/*)
                python_sources+=("$file")
                ;;
        esac
    fi

    # Test file changed directly - include it as-is.
    if [[ "$file" == tests/*.py ]]; then
        add_test "$file"
        continue
    fi

    # Data and automation paths have Python consumers even though the changed
    # files themselves are not Python modules.
    case "$file" in
        alembic/*)
            add_test "tests/persistence"
            continue
            ;;
        scripts/*.py|scripts/*.sh|scripts/lib/*|scripts/quality/*.txt|scripts/quality/*.allowlist)
            add_test "tests/scripts"
            continue
            ;;
        tools/*.py)
            add_test "tests/tools"
            continue
            ;;
    esac

    [[ "$file" == *.py ]] || continue

    # Developer-facing gateway packages live at the repository root instead
    # of under src/fdai, but retain the same mirrored delivery test layout.
    if [[ "$file" == delivery/* ]]; then
        rel="${file#delivery/}"
        sub="${rel%%/*}"
        if [[ "$sub" == "$rel" ]]; then
            candidate="tests/delivery"
        else
            candidate="tests/delivery/${sub}"
        fi
        add_test "$candidate"
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
        continue
    fi

    # A Python change that reaches this point belongs to an unrecognized
    # source layout. Fail safe to the full suite instead of reporting success
    # with no tests selected.
    add_test "tests"
done <<< "$changed"

if [[ ${#python_sources[@]} -gt 0 && -z "${seen[tests]:-}" ]]; then
    while IFS= read -r impacted_test; do
        add_test "$impacted_test"
    done < <(
        python3 "$selector_dir/resolve_test_impact.py" \
            --root "$repo_root" "${python_sources[@]}"
    )
fi

if [[ ${#tests[@]} -eq 0 ]]; then
    exit 0
fi

# Sort and dedupe.
mapfile -t tests < <(printf '%s\n' "${tests[@]}" | sort -u)

# Avoid duplicate pytest collection when both a directory and one of its
# children were selected by different changed files.
selected=()
for path in "${tests[@]}"; do
    covered=0
    for parent in "${selected[@]}"; do
        if [[ "$path" == "$parent"/* ]]; then
            covered=1
            break
        fi
    done
    if [[ $covered -eq 0 ]]; then
        selected+=("$path")
    fi
done
tests=("${selected[@]}")

printf '%s\n' "${tests[@]}"

if [[ $run_pytest -eq 1 ]]; then
    if ! command -v uv >/dev/null 2>&1; then
        echo "tests-for-diff.sh: uv not on PATH; install uv before running tests" >&2
        exit 2
    fi
    echo "--- running pytest on the paths above ---" >&2

    set +e
    uv run pytest -q -m "not integration" --no-cov "${tests[@]}"
    non_integration_status=$?
    set -e
    if [[ $non_integration_status -ne 0 && $non_integration_status -ne 5 ]]; then
        exit "$non_integration_status"
    fi

    if [[ -n "${FDAI_DATABASE_URL:-}" ]]; then
        set +e
        uv run pytest -q -m integration --no-cov "${tests[@]}"
        integration_status=$?
        set -e
        if [[ $integration_status -ne 0 && $integration_status -ne 5 ]]; then
            exit "$integration_status"
        fi
        if [[ $non_integration_status -eq 5 && $integration_status -eq 5 ]]; then
            echo "tests-for-diff.sh: no tests selected for the changed paths" >&2
            exit 5
        fi
        exit 0
    fi

    if [[ $non_integration_status -eq 5 ]]; then
        set +e
        uv run pytest --collect-only -q -m integration --no-cov "${tests[@]}"
        integration_collect_status=$?
        set -e
        if [[ $integration_collect_status -eq 5 ]]; then
            echo "tests-for-diff.sh: no tests selected for the changed paths" >&2
            exit 5
        fi
        if [[ $integration_collect_status -ne 0 ]]; then
            exit "$integration_collect_status"
        fi
    fi

    echo "tests-for-diff.sh: FDAI_DATABASE_URL unset; integration tests skipped" >&2
fi
