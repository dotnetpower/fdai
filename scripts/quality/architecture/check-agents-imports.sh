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
# at the composition root (see docs/roadmap/architecture/csp-neutrality.md).
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
  echo "check-agents-imports: no agents/ Python files - skipping."
  exit 0
fi

banned_re='^[[:space:]]*(from|import)[[:space:]]+(httpx|requests|aiohttp|boto3|azure(\.|[[:space:]])|google\.cloud|fdai\.delivery)'

# Optional allowlist for legitimate exceptions - kept for parity with the
# other two structural gates. Same justification rule (H3): every entry
# MUST be preceded by a '#' comment explaining WHY.
allowlist_file="scripts/.check-agents-imports.allowlist"
declare -A allow_exact=()
allow_globs=()
if [[ -f "$allowlist_file" ]]; then
  prev_was_comment=0
  lineno=0
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    lineno=$((lineno + 1))
    stripped="${raw#"${raw%%[![:space:]]*}"}"
    stripped="${stripped%"${stripped##*[![:space:]]}"}"
    if [[ -z "$stripped" ]]; then
      continue
    fi
    if [[ "$stripped" == \#* ]]; then
      prev_was_comment=1
      continue
    fi
    if (( ! prev_was_comment )); then
      echo "check-agents-imports: allowlist entry '$stripped' at $allowlist_file:$lineno lacks a preceding '#' justification comment" >&2
      exit 2
    fi
    if [[ "$stripped" == *[*?[]* ]]; then
      allow_globs+=("$stripped")
    else
      allow_exact["$stripped"]=1
    fi
    prev_was_comment=0
  done < "$allowlist_file"
fi

declare -A used_exact=()
declare -A used_globs=()

_allowlisted() {
  local p="$1"
  if [[ -n "${allow_exact[$p]:-}" ]]; then
    used_exact["$p"]=1
    return 0
  fi
  local pat
  for pat in "${allow_globs[@]}"; do
    # shellcheck disable=SC2053  # RHS deliberately unquoted for glob
    if [[ "$p" == $pat ]]; then
      used_globs["$pat"]=1
      return 0
    fi
  done
  return 1
}

hit_file="$(mktemp -t check-agents-imports.XXXXXX)"
trap 'rm -f "$hit_file"' EXIT

fail=0
allowlisted=0
for path in "${files[@]}"; do
  if _allowlisted "$path"; then
    allowlisted=$((allowlisted + 1))
    continue
  fi
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

# Stale-allowlist audit - drift protection.
stale=0
for entry in "${!allow_exact[@]}"; do
  if [[ -z "${used_exact[$entry]:-}" ]]; then
    printf 'check-agents-imports: stale allowlist entry (matched nothing): %s\n' "$entry"
    stale=$((stale + 1))
  fi
done
for pat in "${allow_globs[@]}"; do
  if [[ -z "${used_globs[$pat]:-}" ]]; then
    printf 'check-agents-imports: stale allowlist pattern (matched nothing): %s\n' "$pat"
    stale=$((stale + 1))
  fi
done

if (( fail || stale )); then
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

echo "check-agents-imports: OK (${#files[@]} agents/ file(s) scanned, allowlisted=${allowlisted})"
