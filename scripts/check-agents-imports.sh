#!/usr/bin/env bash
#
# check-agents-imports.sh - mirror of check-core-imports.sh, applied to
# src/fdai/agents/.
#
# Rule: the 15 pantheon agents are policy / decision code, not delivery
# code. They MUST NOT import:
#   * any cloud SDK (azure-*, boto3, google.cloud.*)
#   * any HTTP client (httpx, requests, aiohttp)
#   * anything under fdai.delivery.*
#
# A stray transport import in an agent collapses the delivery boundary
# the same way a core violation collapses the CSP boundary. Agents
# reach cloud only through the Protocol seams in fdai.shared.providers.*,
# whose concrete implementations live in fdai.delivery.* and are bound
# at the composition root (see docs/roadmap/csp-neutrality.md).
#
# The check applies to every file under src/fdai/agents/**, including
# the isolated framework layer that G-7 will create at
# src/fdai/agents/_framework/.
#
# Rationale: tracker issue #14 (issue #22).
#
# Regression: 2026-07-11 - added alongside check-file-loc.sh and
# check-subsystem-fanout.sh as the three structural gates the tracker
# requires.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [[ ! -d src/fdai/agents ]]; then
  echo "check-agents-imports: src/fdai/agents/ absent - skipping."
  exit 0
fi

mapfile -t files < <(
  find src/fdai/agents -type f -name '*.py' \
    ! -path '*/__pycache__/*' \
    ! -name '__init__.pyc' \
    | LC_ALL=C sort
)

if (( ${#files[@]} == 0 )); then
  echo "check-agents-imports: no agents/ Python files - skipping."
  exit 0
fi

banned_re='^[[:space:]]*(from|import)[[:space:]]+(httpx|requests|aiohttp|boto3|azure(\.|[[:space:]])|google\.cloud|fdai\.delivery)'

hit_file="$(mktemp -t check-agents-imports.XXXXXX)"
trap 'rm -f "$hit_file"' EXIT

fail=0
for path in "${files[@]}"; do
  if grep -nE "$banned_re" "$path" > "$hit_file" 2>/dev/null; then
    while IFS=: read -r lineno rest; do
      printf '::error file=%s,line=%s::check-agents-imports: forbidden import\n' \
        "$path" "$lineno"
    done < "$hit_file"
    echo "check-agents-imports: forbidden import in $path"
    sed 's/^/  /' "$hit_file"
    fail=1
  fi
done

if (( fail )); then
  cat >&2 <<'EOF'

Fix by routing the offending call through a Protocol in
src/fdai/shared/providers/ and binding the concrete adapter at the
composition root, exactly like the pattern the core layer uses.

Agents are the *judge / responder / auditor* tier of the pantheon
(agent-pantheon.instructions.md); they must not know which SDK
carries the resulting action.
EOF
  exit 1
fi

echo "check-agents-imports: OK (${#files[@]} agents/ file(s) scanned)"
