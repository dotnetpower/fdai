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
#   scripts/automation/tests-for-diff.sh --include-test <nodeid> <range>
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
include_tests=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --run) run_pytest=1 ;;
        --include-test)
            shift
            if [[ $# -eq 0 || -z "$1" ]]; then
                echo "tests-for-diff.sh: --include-test requires a pytest node id" >&2
                exit 2
            fi
            include_tests+=("$1")
            ;;
        -h|--help)
            sed -n '2,22p' "$0"
            exit 0
            ;;
        *)
            if [[ -n "$diff_arg" ]]; then
                echo "tests-for-diff.sh: only one diff range accepted" >&2
                exit 2
            fi
            diff_arg="$1"
            ;;
    esac
    shift
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
full_suite_selected=0

add_test() {
    local path="$1"
    [[ -z "$path" ]] && return 0
    local file_path="${path%%::*}"
    if [[ ! -e "$file_path" ]]; then
        path="tests"
    fi
    if [[ -z "${seen[$path]:-}" ]]; then
        seen[$path]=1
        tests+=("$path")
    fi
}

add_all_tests() {
    local found=0
    local path
    full_suite_selected=1
    for path in services/*/tests packages/*/tests tests/integration; do
        [[ -e "$path" ]] || continue
        add_test "$path"
        found=1
    done
    if [[ $found -eq 0 ]]; then
        add_test "tests"
    fi
}

while IFS= read -r file; do
    [[ -z "$file" ]] && continue

    # These inputs can affect collection or every Python test. Selecting the
    # full suite is cheaper than silently missing a cross-cutting regression.
    case "$file" in
        config/service-decomposition.json|config/independent-services.json)
            if [[ -d tests/integration/scripts ]]; then
                add_test "tests/integration/scripts"
            else
                add_test "tests/scripts"
            fi
            continue
            ;;
        .github/workflows/ci.yml|Dockerfile|Makefile|alembic.ini|pyproject.toml|uv.lock|tests/integration/conftest.py)
            add_all_tests
            continue
            ;;
        alembic/*|config/*|policies/*|rule-catalog/*)
            add_all_tests
            continue
            ;;
        packages/service-contracts/*|services/core-control-plane/src/fdai/composition/*|services/core-control-plane/src/fdai/rule_catalog/*|services/core-control-plane/src/fdai/shared/contracts/*|services/core-control-plane/src/fdai/shared/providers/*)
            add_all_tests
            continue
            ;;
        extensions/code-assurance/*)
            add_test "extensions/code-assurance/tests"
            continue
            ;;
    esac

    if [[ ("$file" == tests/* || "$file" == services/*/src/* || "$file" == services/*/tests/* || "$file" == packages/*/src/* || "$file" == packages/*/tests/* || "$file" == src/*) && "$file" != *.py ]]; then
        add_all_tests
        continue
    fi

    if [[ "$file" == *.py ]]; then
        case "$file" in
            services/*/src/*|packages/*/src/*|services/core-control-plane/src/fdai/*|delivery/*|scripts/*|tools/*)
                python_sources+=("$file")
                ;;
        esac
    fi

    # Test file changed directly - include it as-is.
    if [[ "$file" == tests/integration/*.py || "$file" == services/*/tests/*.py || "$file" == packages/*/tests/*.py || "$file" == tests/*.py ]]; then
        add_test "$file"
        continue
    fi

    # Data and automation paths have Python consumers even though the changed
    # files themselves are not Python modules.
    case "$file" in
        scripts/*.py|scripts/*.sh|scripts/lib/*|scripts/quality/*.txt|scripts/quality/*.allowlist)
            if [[ -d tests/integration/scripts ]]; then
                add_test "tests/integration/scripts"
            else
                add_test "tests/scripts"
            fi
            continue
            ;;
        tools/*.py)
            add_test "services/core-control-plane/tests/tools"
            continue
            ;;
    esac

    [[ "$file" == *.py ]] || continue

    if [[ "$file" == services/*/src/* ]]; then
        service_root="${file%%/src/*}"
        add_test "$service_root/tests"
        continue
    fi

    if [[ "$file" == packages/*/src/* ]]; then
        add_all_tests
        continue
    fi

    # Developer-facing gateway packages live at the repository root instead
    # of under src/fdai, but retain the same mirrored delivery test layout.
    if [[ "$file" == delivery/* ]]; then
        rel="${file#delivery/}"
        sub="${rel%%/*}"
        if [[ "$sub" == "$rel" ]]; then
            candidate="tests/delivery"
        else
            candidate="services/core-control-plane/tests/delivery/${sub}"
        fi
        add_test "$candidate"
        continue
    fi

    # Source file - map to the mirrored test path.
    #   services/core-control-plane/src/fdai/core/<sub>/*.py            -> services/core-control-plane/tests/core/<sub>/
    #   services/core-control-plane/src/fdai/agents/*.py                -> services/core-control-plane/tests/agents/
    #   services/core-control-plane/src/fdai/delivery/<sub>/*.py        -> services/core-control-plane/tests/delivery/<sub>/
    #   services/core-control-plane/src/fdai/shared/<sub>/*.py          -> services/core-control-plane/tests/shared/<sub>/
    #   services/core-control-plane/src/fdai/rule_catalog/*.py          -> services/core-control-plane/tests/rule_catalog/
    #   services/core-control-plane/src/fdai/composition/*.py           -> services/core-control-plane/tests/composition/
    if [[ "$file" == services/core-control-plane/src/fdai/* ]]; then
        rel="${file#services/core-control-plane/src/fdai/}"           # e.g. core/risk_gate/foo.py
        first="${rel%%/*}"                # core
        rest="${rel#*/}"                  # risk_gate/foo.py
        if [[ "$rest" == "$rel" ]]; then
            # Flat file directly under services/core-control-plane/src/fdai/
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
    add_all_tests
done <<< "$changed"

if [[ ${#python_sources[@]} -gt 0 && -z "${seen[tests]:-}" ]]; then
    impact_resolver="${FDAI_TEST_IMPACT_RESOLVER:-$selector_dir/resolve_test_impact.py}"
    ownership_resolver="${FDAI_TEST_OWNERSHIP_RESOLVER:-$selector_dir/resolve_test_ownership.py}"
    ownership_threshold="${FDAI_TEST_IMPACT_SERVICE_THRESHOLD:-250}"
    if [[ ! "$ownership_threshold" =~ ^[1-9][0-9]*$ ]]; then
        echo "tests-for-diff.sh: FDAI_TEST_IMPACT_SERVICE_THRESHOLD must be a positive integer" >&2
        exit 2
    fi
    set +e
    impacted_output=$(
        python3 "$impact_resolver" --root "$repo_root" "${python_sources[@]}"
    )
    impact_status=$?
    set -e
    if [[ $impact_status -ne 0 ]]; then
        echo "tests-for-diff.sh: impact resolver failed with status $impact_status" >&2
        exit "$impact_status"
    fi
    mapfile -t impacted_tests < <(printf '%s\n' "$impacted_output" | sed '/^$/d')
    owned_output=""
    if [[ ${#impacted_tests[@]} -ge $ownership_threshold ]]; then
        set +e
        owned_output=$(
            python3 "$ownership_resolver" --root "$repo_root" "${python_sources[@]}"
        )
        ownership_status=$?
        set -e
        if [[ $ownership_status -ne 0 ]]; then
            echo "tests-for-diff.sh: ownership resolver failed; using import impact" >&2
            owned_output=""
        fi
    fi
    selected_impact="$impacted_output"
    if [[ -n "$owned_output" ]]; then
        selected_impact=$(printf '%s\n%s\n' "$owned_output" "$impacted_output")
        echo "tests-for-diff.sh: broad import impact compressed with service-owned suites" >&2
    fi
    while IFS= read -r impacted_test; do
        add_test "$impacted_test"
    done <<< "$selected_impact"
fi

for test_nodeid in "${include_tests[@]}"; do
    add_test "$test_nodeid"
done

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
        path_file="${path%%::*}"
        parent_file="${parent%%::*}"
        if [[ "$path" != "$path_file" ]] && \
            [[ "$path_file" == "$parent_file" || "$path_file" == "$parent_file"/* ]]; then
            covered=1
            break
        fi
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

    parallel_args=()
    pytest_cache_args=()
    if [[ -n "${FDAI_CHANGED_TEST_CACHE_DIR:-}" ]]; then
        pytest_cache_args=(-o "cache_dir=$FDAI_CHANGED_TEST_CACHE_DIR")
    fi
    parallel_threshold="${FDAI_CHANGED_TEST_PARALLEL_THRESHOLD:-20}"
    if [[ ! "$parallel_threshold" =~ ^[1-9][0-9]*$ ]]; then
        echo "tests-for-diff.sh: FDAI_CHANGED_TEST_PARALLEL_THRESHOLD must be a positive integer" >&2
        exit 2
    fi
    if [[ "${FDAI_PYTEST_XDIST:-1}" == "1" ]] && \
        [[ $full_suite_selected -eq 1 || -n "${seen[tests]:-}" || ${#tests[@]} -ge $parallel_threshold ]]; then
        parallel_args=(
            -n auto
            --maxprocesses="${FDAI_PYTEST_MAX_WORKERS:-8}"
            --dist=worksteal
        )
    fi
    pytest_roots=()
    if [[ -d "$repo_root/packages/service-contracts/src" ]]; then
        pytest_roots+=("$repo_root/packages/service-contracts/src")
    fi
    for source_root in "$repo_root"/services/*/src; do
        [[ -d "$source_root" ]] && pytest_roots+=("$source_root")
    done
    if [[ ${#pytest_roots[@]} -eq 0 ]]; then
        pytest_roots+=("$repo_root/src")
    fi
    pytest_pythonpath=$(IFS=:; printf '%s' "${pytest_roots[*]}")
    if [[ -n "${PYTHONPATH:-}" ]]; then
        pytest_pythonpath="$pytest_pythonpath:$PYTHONPATH"
    fi
    clean_pytest_env=(
        env
        -u RUNTIME_ENV
        -u DATABASE_URL
        -u POSTGRES_URL
        -u AZURE_CONFIG_DIR
    )
    while IFS='=' read -r name _value; do
        if [[ "$name" == FDAI_* ]]; then
            clean_pytest_env+=(-u "$name")
        fi
    done < <(env)
    run_integration="${FDAI_CHANGED_TEST_INTEGRATION:-0}"
    if [[ "$run_integration" != "0" && "$run_integration" != "1" ]]; then
        echo "tests-for-diff.sh: FDAI_CHANGED_TEST_INTEGRATION must be 0 or 1" >&2
        exit 2
    fi

    set +e
    "${clean_pytest_env[@]}" PYTHONPATH="$pytest_pythonpath" \
        uv run pytest -q -m "not integration" --no-cov "${pytest_cache_args[@]}" \
        "${parallel_args[@]}" "${tests[@]}"
    non_integration_status=$?
    set -e
    if [[ $non_integration_status -ne 0 && $non_integration_status -ne 5 ]]; then
        exit "$non_integration_status"
    fi

    if [[ "$run_integration" == "1" ]]; then
        if [[ -z "${FDAI_DATABASE_URL:-}" ]]; then
            echo "tests-for-diff.sh: FDAI_DATABASE_URL is required when integration is enabled" >&2
            exit 2
        fi
        set +e
        "${clean_pytest_env[@]}" FDAI_DATABASE_URL="$FDAI_DATABASE_URL" \
            PYTHONPATH="$pytest_pythonpath" \
            uv run pytest -q -m integration --no-cov "${pytest_cache_args[@]}" "${tests[@]}"
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
        "${clean_pytest_env[@]}" PYTHONPATH="$pytest_pythonpath" \
            uv run pytest --collect-only -q -m integration --no-cov \
            "${pytest_cache_args[@]}" "${tests[@]}"
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

    echo "tests-for-diff.sh: integration tests skipped; set FDAI_CHANGED_TEST_INTEGRATION=1 with a disposable FDAI_DATABASE_URL to run them" >&2
fi
