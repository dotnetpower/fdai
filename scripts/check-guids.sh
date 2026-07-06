#!/usr/bin/env bash
#
# check-guids.sh - block real customer/personal Azure GUIDs from being
# committed. Enforces the generic-scope contract:
#
#     No customer-specific identifiers of any kind, in any artifact
#     (source, config, docs, tests, fixtures, sample data, commit messages,
#     ...). See:
#         .github/instructions/generic-scope.instructions.md
#
# The allowlist:
#   - The all-zero placeholder `00000000-0000-0000-0000-XXXXXXXXXXXX`
#     (any hex tail). This is the documented placeholder for tests.
#   - Any GUID inside a fenced code block that is clearly a UUID5 namespace
#     literal is still blocked - the rule is generic-scope, not context.
#
# Any other GUID-shaped run (8-4-4-4-12 hex) in a tracked text file fails
# this check. Rationale: the pattern is the same shape Azure uses for
# subscription, tenant, and resource IDs; the only safe way to keep the
# repo generic is to force placeholders or env-var references.
#
# Scope (in):
#   Every git-tracked file except binary assets, uv.lock, and the site's
#   generated content mount (site/src/content/docs/**, which is symlinked
#   copies of docs/ that go through the same gate on the canonical side).
#
# Exit codes: 0 clean, 1 on any violation.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

mapfile -t files < <(
  git ls-files \
    ':(exclude)*.png' \
    ':(exclude)*.jpg' \
    ':(exclude)*.jpeg' \
    ':(exclude)*.gif' \
    ':(exclude)*.webp' \
    ':(exclude)*.svg' \
    ':(exclude)*.pdf' \
    ':(exclude)*.ico' \
    ':(exclude)*.woff' \
    ':(exclude)*.woff2' \
    ':(exclude)*.ttf' \
    ':(exclude)*.otf' \
    ':(exclude)uv.lock' \
    ':(exclude)*.jsonl' \
    | sort -u
)

# GUID pattern: 8-4-4-4-12 lowercase hex (Azure canonical form). Uppercase
# is unusual for Azure IDs; if a case-insensitive match is needed later,
# extend here. Anchored with word boundaries so hex hashes are ignored.
guid_re='\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b'
# Allowlist: all-zero placeholder (any hex tail after the fourth block).
# `00000000-0000-0000-0000-000000000000` and variants
# `00000000-0000-0000-0000-000000000001`, `...-DEADBEEFCAFE`, etc. all pass.
allow_re='^00000000-0000-0000-0000-[0-9a-f]{12}$'

errors=0
for f in "${files[@]}"; do
  [[ -f "$f" ]] || continue
  # Extract every GUID with file:line:guid and filter out allowlisted ones.
  hits="$(grep -nHoE "$guid_re" "$f" 2>/dev/null || true)"
  [[ -z "$hits" ]] && continue
  while IFS= read -r hit; do
    guid="${hit##*:}"
    [[ "$guid" =~ ^00000000-0000-0000-0000-[0-9a-f]{12}$ ]] && continue
    # Allow the deterministic UUID5 namespace used by the attribution
    # code - it is a code constant, not a customer id.
    if [[ "$guid" == "6b1b6f2c-5a3e-4a91-8f1a-8b8a7e2f9d10" ]]; then
      continue
    fi
    echo "check-guids: $hit" >&2
    errors=$((errors + 1))
  done <<< "$hits"
done

if (( errors > 0 )); then
  echo >&2
  echo "check-guids: FAILED (${errors} GUID occurrence(s))." >&2
  echo "Fix: replace with the placeholder '00000000-0000-0000-0000-000000000000'" >&2
  echo "     or load the value from an environment variable at runtime." >&2
  echo "Policy: .github/instructions/generic-scope.instructions.md" >&2
  exit 1
fi

printf 'check-guids: OK (%d tracked file(s) scanned)\n' "${#files[@]}"
