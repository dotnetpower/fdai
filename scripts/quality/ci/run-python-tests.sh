#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

coverage_args=(
  --cov
  --cov-branch
  --cov-report=term-missing
  --cov-report=xml
  --cov-fail-under=90
)

parallel_args=()
if [[ "${FDAI_PYTEST_XDIST:-1}" == "1" ]]; then
  parallel_args=(
    -n auto
    --maxprocesses="${FDAI_PYTEST_MAX_WORKERS:-8}"
    --dist=worksteal
  )
fi

uv run pytest -q -m "not integration" --durations=25 \
  "${parallel_args[@]}" "${coverage_args[@]}" "$@"

if [[ -n "${FDAI_DATABASE_URL:-}" && $# -eq 0 ]]; then
  uv run pytest -q -m integration --no-cov --durations=25
elif [[ $# -eq 0 ]]; then
  printf '%s\n' "python-tests: FDAI_DATABASE_URL unset; integration tests skipped"
fi
