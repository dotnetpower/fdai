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

    if [[ ("$file" == services/*/src/* || "$file" == packages/*/src/*) && "$file" != *.py ]]; then
        owner_root="${file%%/src/*}"
        add_test "$owner_root/tests"
        continue
    fi

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
        core_test_root="services/core-control-plane/tests"
        rel="${file#services/core-control-plane/src/fdai/}"           # e.g. core/risk_gate/foo.py
        first="${rel%%/*}"                # core
        rest="${rel#*/}"                  # risk_gate/foo.py
        if [[ "$rest" == "$rel" ]]; then
            # Flat file directly under services/core-control-plane/src/fdai/
            candidate="$core_test_root"
        else
            case "$first" in
                core|delivery|shared)
                    sub="${rest%%/*}"     # risk_gate
                    if [[ "$sub" == "$rest" ]]; then
                        candidate="$core_test_root/${first}"
                    else
                        candidate="$core_test_root/${first}/${sub}"
                    fi
                    ;;
                agents|rule_catalog|composition)
                    candidate="$core_test_root/${first}"
                    ;;
                *)
                    candidate="$core_test_root"
                    ;;
            esac
        fi
        if [[ -e "$candidate" ]]; then
            add_test "$candidate"
        else
            add_test "$core_test_root"
        fi
        continue
    fi

    if [[ "$file" == services/*/src/* ]]; then
        service_root="${file%%/src/*}"
        add_test "$service_root/tests"
        continue
    fi

    if [[ "$file" == packages/*/src/* ]]; then
        add_all_tests
        continue
    fi

    # A Python change that reaches this point belongs to an unrecognized
    # source layout. Fail safe to the full suite instead of reporting success
    # with no tests selected.
    add_all_tests
done <<< "$changed"

if [[ ${#python_sources[@]} -gt 0 && $full_suite_selected -eq 0 && -z "${seen[tests]:-}" ]]; then
    impact_resolver="${FDAI_TEST_IMPACT_RESOLVER:-$selector_dir/resolve_test_impact.py}"
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
    while IFS= read -r impacted_test; do
        add_test "$impacted_test"
    done <<< "$impacted_output"
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
declare -A selected_dirs=()
declare -A selected_files=()
for path in "${tests[@]}"; do
    covered=0
    path_file="${path%%::*}"
    if [[ "$path" != "$path_file" && -n "${selected_files[$path_file]:-}" ]]; then
        covered=1
    fi
    ancestor="$path_file"
    while [[ $covered -eq 0 && "$ancestor" == */* ]]; do
        ancestor="${ancestor%/*}"
        if [[ -n "${selected_dirs[$ancestor]:-}" ]]; then
            covered=1
            break
        fi
    done
    if [[ $covered -eq 0 ]]; then
        selected+=("$path")
        if [[ "$path" == "$path_file" ]]; then
            if [[ -d "$path_file" ]]; then
                selected_dirs["$path_file"]=1
            else
                selected_files["$path_file"]=1
            fi
        fi
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

    parallel_threshold="${FDAI_CHANGED_TEST_PARALLEL_THRESHOLD:-20}"
    if [[ ! "$parallel_threshold" =~ ^[1-9][0-9]*$ ]]; then
        echo "tests-for-diff.sh: FDAI_CHANGED_TEST_PARALLEL_THRESHOLD must be a positive integer" >&2
        exit 2
    fi
    broad_directory_selected=0
    for path in "${tests[@]}"; do
        file_path="${path%%::*}"
        [[ -d "$file_path" ]] || continue
        test_file_count=0
        while IFS= read -r _test_file; do
            ((test_file_count += 1))
            (( test_file_count >= parallel_threshold )) && break
        done < <(find "$file_path" -type f -name 'test_*.py' -print)
        if (( test_file_count >= parallel_threshold )); then
            broad_directory_selected=1
            break
        fi
    done
    shard_count=1
    if [[ "${FDAI_PYTEST_XDIST:-1}" == "1" ]] && \
        [[ $full_suite_selected -eq 1 || $broad_directory_selected -eq 1 || -n "${seen[tests]:-}" || ${#tests[@]} -ge $parallel_threshold ]]; then
        shard_count="${FDAI_PYTEST_MAX_WORKERS:-4}"
        if [[ ! "$shard_count" =~ ^[1-9][0-9]*$ ]]; then
            echo "tests-for-diff.sh: FDAI_PYTEST_MAX_WORKERS must be a positive integer" >&2
            exit 2
        fi
        (( shard_count > 4 )) && shard_count=4
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
    run_integration="${FDAI_CHANGED_TEST_INTEGRATION:-0}"
    if [[ "$run_integration" != "0" && "$run_integration" != "1" ]]; then
        echo "tests-for-diff.sh: FDAI_CHANGED_TEST_INTEGRATION must be 0 or 1" >&2
        exit 2
    fi

    shard_cache_root="${FDAI_CHANGED_TEST_CACHE_DIR:-$repo_root/.pytest_cache/fdai-changed-tests}"
    shard_result_root="${FDAI_CHANGED_TEST_SHARD_DIR:-$repo_root/.pytest_cache/fdai-changed-test-results}"
    PYTHONPATH="$pytest_pythonpath" python3 "$selector_dir/run-changed-test-shards.py" \
        --shard-count "$shard_count" \
        --cache-root "$shard_cache_root" \
        --result-root "$shard_result_root" \
        --integration "$run_integration" \
        "${tests[@]}"
fi
