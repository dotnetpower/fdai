#!/usr/bin/env bash
#
# check-core-imports.sh - enforce the module-boundary rule that keeps the
# control-plane CSP-neutral and UI-agnostic.
#
# Rule (see docs/roadmap/architecture/project-structure.md § Module Boundaries and
# .github/copilot-instructions.md § Implementation Focus):
#
#   src/fdai/core/** MUST NOT import:
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
  find src/fdai/core -type f -name '*.py' \
    ! -path '*/__pycache__/*' \
    ! -name '__init__.pyc' \
    | sort
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
while IFS= read -r path; do
  if grep -nE "$banned_re" "$path" > /tmp/core-import-hit 2>/dev/null; then
    echo "check-core-imports: forbidden import in $path"
    sed 's/^/  /' /tmp/core-import-hit
    fail=1
  fi
done < <(printf '%s\n' "${files[@]}")

rm -f /tmp/core-import-hit

if (( fail )); then
  cat >&2 <<'EOF'

Fix by moving the offending SDK / HTTP / delivery adapter call behind
one of the CSP-neutral Protocols in src/fdai/shared/providers/
(see docs/roadmap/architecture/csp-neutrality.md § 1-5) and binding the concrete
implementation at the composition root.
EOF
  exit 1
fi

echo "check-core-imports: OK (${#files[@]} core/ file(s) scanned)"
