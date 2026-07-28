#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

coverage_args=(
  --cov
  --cov-branch
  --cov-report=term-missing
  --cov-report=xml
  --cov-fail-under=90
)

coverage_paths=(
  tests/core
  tests/pipeline
  tests/scenarios
  tests/verticals
  tests/delivery/test_canary_cli.py
)

parallel_args=()
if [[ "${FDAI_PYTEST_XDIST:-1}" == "1" ]]; then
  parallel_args=(
    -n auto
    --maxprocesses="${FDAI_PYTEST_MAX_WORKERS:-8}"
    --dist=worksteal
  )
fi

shard_args=()
if [[ -n "${FDAI_PYTEST_SHARD_COUNT:-}" || -n "${FDAI_PYTEST_SHARD_INDEX:-}" ]]; then
  if [[ -z "${FDAI_PYTEST_SHARD_COUNT:-}" || -z "${FDAI_PYTEST_SHARD_INDEX:-}" ]]; then
    printf '%s\n' "python-tests: shard count and index must be set together" >&2
    exit 2
  fi
  shard_args=(-p scripts.quality.ci.pytest_shard)
fi

mode="${FDAI_PYTEST_MODE:-all}"
case "$mode" in
  all)
    env -u FDAI_DATABASE_URL -u FDAI_STATE_STORE_DSN \
      uv run pytest -q -m "not integration" --durations=25 \
      "${parallel_args[@]}" "${coverage_args[@]}" "$@"
    if [[ -n "${FDAI_DATABASE_URL:-}" && $# -eq 0 ]]; then
      uv run pytest -q -m integration --no-cov --durations=25
    elif [[ $# -eq 0 ]]; then
      printf '%s\n' "python-tests: FDAI_DATABASE_URL unset; integration tests skipped"
    fi
    ;;
  full)
    env -u FDAI_DATABASE_URL -u FDAI_STATE_STORE_DSN \
      uv run pytest -q -m "not integration" --no-cov --durations=25 \
      "${parallel_args[@]}" "${shard_args[@]}" "$@"
    ;;
  coverage)
    env -u FDAI_DATABASE_URL -u FDAI_STATE_STORE_DSN \
      uv run pytest -q -m "not integration" --durations=25 \
      "${parallel_args[@]}" "${coverage_args[@]}" "${coverage_paths[@]}" "$@"
    ;;
  integration)
    if [[ -z "${FDAI_DATABASE_URL:-}" ]]; then
      printf '%s\n' "python-tests: FDAI_DATABASE_URL is required for integration mode" >&2
      exit 2
    fi
    uv run pytest -q -m integration --no-cov --durations=25 "$@"
    ;;
  *)
    printf '%s\n' "python-tests: unknown FDAI_PYTEST_MODE=$mode" >&2
    exit 2
    ;;
esac
