#!/usr/bin/env bash
#
# local-preflight.sh - run locally the CI jobs that a diff would trigger.
#
# GitHub Actions is final integration evidence, not an edit-loop test runner.
# This script reuses the same change-scope resolver as the CI `changes` job
# (scripts/quality/ci/resolve_test_scope.py) and runs the matching local gates
# on the committed range, so deterministic failures surface before a push.
#
# Usage:
#   scripts/quality/ci/local-preflight.sh [--base <ref>] [--fail-fast] [--skip-lint]
#   make ci-preflight [BASE=origin/main]
#
# CI-only jobs are not reproduced here: sharded pytest, the database
# integration shards, the safety-core coverage floor, gitleaks, pip-audit, and
# the frozen-scenario check. Exit 0 means the local subset passed.

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root" || exit 1

base="origin/main"
fail_fast=0
skip_lint=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) base="${2:?--base requires a ref}"; shift 2 ;;
    --fail-fast) fail_fast=1; shift ;;
    --skip-lint) skip_lint=1; shift ;;
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "local-preflight: unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Prefer the locked virtual environment so system Python without the
# project's dependencies cannot report a false gate failure.
if [[ -x .venv/bin/python ]]; then
  export PATH="$repo_root/.venv/bin:$PATH"
else
  echo "local-preflight: .venv is missing; run 'uv sync --extra dev --frozen' first." >&2
  exit 2
fi
if ! python -c "import yaml" 2>/dev/null; then
  echo "local-preflight: .venv lacks project dependencies; run 'uv sync --extra dev --frozen'." >&2
  exit 2
fi

remote="${base%%/*}"
branch="${base#*/}"
if [[ "$remote" != "$base" ]] && git remote get-url "$remote" >/dev/null 2>&1; then
  git fetch --quiet "$remote" "$branch" || echo "local-preflight: fetch failed; using the cached $base." >&2
fi
if ! git rev-parse --verify --quiet "$base" >/dev/null; then
  echo "local-preflight: base ref not found: $base" >&2
  exit 2
fi

behind="$(git rev-list --count "HEAD..$base")"
if [[ "$behind" != "0" ]]; then
  echo "local-preflight: BLOCKED - HEAD is $behind commit(s) behind $base." >&2
  echo "  Merge it first (git merge $base), otherwise CI runs a second attempt after the base update." >&2
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "local-preflight: note - uncommitted changes exist; only the committed range $base...HEAD is classified."
fi

range="$base...HEAD"
scope_file="$(mktemp)"
trap 'rm -f "$scope_file"' EXIT
GITHUB_OUTPUT="$scope_file" python scripts/quality/ci/resolve_test_scope.py --range "$range" || exit 2
scope() { grep -qx "$1=true" "$scope_file"; }
echo "local-preflight: range $range"
echo "local-preflight: scope $(tr '\n' ' ' <"$scope_file")"

results=()
failed=0
run_step() {
  local label="$1"
  shift
  local started=$SECONDS
  echo
  echo "=== $label ==="
  "$@"
  local rc=$?
  local elapsed=$((SECONDS - started))
  if [[ $rc -eq 0 ]]; then
    results+=("PASS  ${elapsed}s  $label")
  else
    results+=("FAIL  ${elapsed}s  $label")
    failed=1
    if [[ $fail_fast -eq 1 ]]; then
      summarize
      exit 1
    fi
  fi
}
skip_step() { results+=("SKIP  -     $1 ($2)"); }
summarize() {
  echo
  echo "=== local-preflight summary ($range) ==="
  printf '%s\n' "${results[@]}"
}

run_step "static contracts and hygiene (verify.sh --fast)" bash scripts/verify.sh --fast --diff "$range"
run_step "file LOC (enforce)" env FILE_LOC_MODE=enforce bash scripts/quality/architecture/check-file-loc.sh
run_step "subsystem fan-out (enforce)" env SUBSYSTEM_FANOUT_MODE=enforce bash scripts/quality/architecture/check-subsystem-fanout.sh
run_step "documentation links" bash scripts/quality/repository/check-doc-links.sh

if scope python; then
  if [[ $skip_lint -eq 1 ]]; then
    skip_step "ruff + mypy" "--skip-lint"
  else
    run_step "ruff format, ruff check, mypy" make lint
  fi
  run_step "pytest for changed paths" make test-changed DIFF="$range"
else
  skip_step "ruff + mypy + pytest" "no Python-scoped change"
fi

if scope operator; then
  if [[ ! -d console/node_modules || ! -d cli/node_modules ]]; then
    run_step "install locked console and CLI dependencies" bash -c \
      'npm --prefix console ci --no-audit --no-fund && npm --prefix cli ci --no-audit --no-fund'
  fi
  run_step "console and CLI tests, typecheck, build" make operator
else
  skip_step "console and CLI" "no operator-scoped change"
fi

if scope terraform; then
  if command -v terraform >/dev/null 2>&1; then
    run_step "terraform fmt -check" terraform fmt -check -recursive infra
  else
    skip_step "terraform fmt" "terraform not installed"
  fi
else
  skip_step "terraform" "no infra change"
fi

summarize
if [[ $failed -ne 0 ]]; then
  echo "local-preflight: FAILED - fix locally and push once."
  exit 1
fi
echo "local-preflight: OK (CI-only jobs listed in the header still run on GitHub)."
