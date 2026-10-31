#!/usr/bin/env bash
#
# check-core-imports.sh - enforce the module-boundary rule that keeps the
# control-plane CSP-neutral and UI-agnostic.
#
# Rule (see docs/roadmap/architecture/project-structure.md § Module Boundaries and
# .github/copilot-instructions.md § Implementation Focus):
#
#   services/core-control-plane/src/fdai/core/** MUST NOT import:
#     * any cloud SDK (azure-*, boto3, google.cloud.*)
#     * any HTTP client (httpx, requests, aiohttp)
#     * anything under fdai.delivery.*
#
# The reason is the CSP-neutrality contract set in
# docs/roadmap/architecture/csp-neutrality.md: every cloud-touching call goes through
# a Protocol under fdai.shared.providers.*, whose concrete
# implementations live in fdai.delivery.* and are bound at the
# composition root. A stray `import httpx` inside core/ collapses that
# separation and re-locks the runtime to a specific transport.
#
# Exit codes: 0 on clean, 1 on any violation.
#
# Regression: 2026-07-05 audit - critique G2. Ships alongside the
# safety-core coverage floor (G1) and the ontology seeding (G4).

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

# Every Python module under core/, whether tracked, modified, or freshly
# added. Walking the filesystem (not `git ls-files`) means an
# uncommitted edit that introduces a banned import still fails locally
# - matching the developer expectation for pre-commit / pre-push hooks.
mapfile -t files < <(
  find services/core-control-plane/src/fdai/core -type f -name '*.py' \
    ! -path '*/__pycache__/*' \
    ! -path '*/.pytest_cache/*' \
    ! -path '*/.mypy_cache/*' \
    ! -path '*/.ruff_cache/*' \
    ! -path '*/.tox/*' \
    ! -path '*/.venv/*' \
    ! -path '*/venv/*' \
    ! -path '*/.git/*' \
    ! -name '__init__.pyc' \
    | LC_ALL=C sort
)

if (( ${#files[@]} == 0 )); then
  echo "check-core-imports: no core/ Python files tracked yet - skipping."
  exit 0
fi

# One extended regex per banned line shape. Each pattern captures either
# `import X` or `from X ...`. Comments and docstrings are ignored - we
# only reject actual import statements.
banned_re='^[[:space:]]*(from|import)[[:space:]]+(httpx|requests|aiohttp|boto3|azure(\.|[[:space:]])|google\.cloud|fdai\.delivery)'

fail=0
if grep_hits="$(grep -nHE "$banned_re" "${files[@]}" 2>/dev/null)"; then
  fail=1
  current_file=""
  while IFS=: read -r hit_path hit_line hit_rest; do
    [[ -n "$hit_path" ]] || continue
    if [[ "$hit_path" != "$current_file" ]]; then
      echo "check-core-imports: forbidden import in $hit_path"
      current_file="$hit_path"
    fi
    printf '  %s:%s\n' "$hit_line" "$hit_rest"
  done <<< "$grep_hits"
fi

if (( fail )); then
  cat >&2 <<'EOF'

Fix by moving the offending SDK / HTTP / delivery adapter call behind
one of the CSP-neutral Protocols in services/core-control-plane/src/fdai/shared/providers/
(see docs/roadmap/architecture/csp-neutrality.md § 1-5) and binding the concrete
implementation at the composition root.
EOF
  exit 1
fi

echo "check-core-imports: OK (${#files[@]} core/ file(s) scanned)"
