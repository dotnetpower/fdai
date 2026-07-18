#!/usr/bin/env bash
#
# check-file-loc.sh - LOC-per-file guidance from
# .github/instructions/coding-conventions.instructions.md
# ("Prefer files under ~400 lines") turned into a mechanical gate.
#
# Two thresholds:
#   * warn > 400 LOC  - flagged, exit 0 in warn-only mode
#   * fail > 800 LOC  - flagged, exit 1 unless in warn-only mode
#
# Modes:
#   FILE_LOC_MODE=warn (default)  - only warn, never fail
#   FILE_LOC_MODE=enforce         - warn + fail on > 800
#
# Environment overrides (kept small on purpose):
#   FILE_LOC_WARN=400   - warn threshold
#   FILE_LOC_FAIL=800   - fail threshold
#
# Scope: src/fdai/**/*.py only. Excludes tests, migrations, third-party,
# generated code, and __pycache__.
#
# Allowlist: scripts/.check-file-loc.allowlist (one path per line, '#'
# comments, blanks ignored). Each entry MUST document *why* it is
# exempt in a comment on the preceding line. An allowlisted file is
# skipped entirely.
#
# Rationale: tracker issue #14 (issue #22). The refactor items G-2, G-3,
# G-4, G-5 all exist because a handful of files crossed the 600-800 LOC
# threshold and became god-objects; this script prevents drift after
# those refactors land.
#
# Regression: 2026-07-11 - added alongside check-agents-imports.sh and
# check-subsystem-fanout.sh as the three structural gates the tracker
# requires (issue #22).

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

warn_thresh="${FILE_LOC_WARN:-400}"
fail_thresh="${FILE_LOC_FAIL:-800}"
mode="${FILE_LOC_MODE:-warn}"
quiet="${CHECK_QUIET:-0}"

if ! [[ "$warn_thresh" =~ ^[0-9]+$ && "$fail_thresh" =~ ^[0-9]+$ ]]; then
  echo "check-file-loc: FILE_LOC_WARN/FILE_LOC_FAIL must be integers" >&2
  exit 2
fi
if (( warn_thresh >= fail_thresh )); then
  echo "check-file-loc: FILE_LOC_WARN ($warn_thresh) must be < FILE_LOC_FAIL ($fail_thresh)" >&2
  exit 2
fi

# Two containers so glob patterns keep their intent (matched with
# bash's own filename matching, not literal string lookup):
#   allow_exact[path]=1     - literal path match
#   allow_globs=("pat" ...) - patterns containing * ? or [
allowlist_file="scripts/.check-file-loc.allowlist"
declare -A allow_exact=()
allow_globs=()
if [[ -f "$allowlist_file" ]]; then
  # Each real entry MUST be preceded (on the immediately previous non-blank
  # line) by a '#' comment explaining WHY the file is exempt. An entry
  # without justification is a governance smell and is rejected loudly.
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
      echo "check-file-loc: allowlist entry '$stripped' at $allowlist_file:$lineno lacks a preceding '#' justification comment" >&2
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

declare -A used_exact=()
declare -A used_globs=()

# Deterministic ordering; excludes __pycache__ and the common Python
# tool-cache / virtualenv dot-dirs. The generic exclusion keeps the
# gate honest when a developer runs it inside a repo that also carries
# .pytest_cache/ or a nested .venv (checked-out for a debug session).
mapfile -t files < <(
  find src/fdai -type f -name '*.py' \
    ! -path '*/__pycache__/*' \
    ! -path '*/.pytest_cache/*' \
    ! -path '*/.mypy_cache/*' \
    ! -path '*/.ruff_cache/*' \
    ! -path '*/.tox/*' \
    ! -path '*/.venv/*' \
    ! -path '*/venv/*' \
    ! -path '*/.git/*' \
    | LC_ALL=C sort
)

if (( ${#files[@]} == 0 )); then
  echo "check-file-loc: no src/fdai Python files - skipping."
  exit 0
fi

warned=0
failed=0
scanned=0
allowlisted=0

for path in "${files[@]}"; do
  if _allowlisted "$path"; then
    allowlisted=$((allowlisted + 1))
    continue
  fi
  scanned=$((scanned + 1))
  loc=$(wc -l < "$path")
  if (( loc > fail_thresh )); then
    # GitHub Actions annotation so PR Files tab highlights the file.
    printf '::warning file=%s,line=1::check-file-loc: %d LOC exceeds fail threshold %d\n' \
      "$path" "$loc" "$fail_thresh"
    if [[ "$quiet" != "1" ]]; then
      printf 'check-file-loc: FAIL  %5d LOC  %s (> %d)\n' \
        "$loc" "$path" "$fail_thresh"
    fi
    failed=$((failed + 1))
  elif (( loc > warn_thresh )); then
    printf '::notice file=%s,line=1::check-file-loc: %d LOC exceeds warn threshold %d\n' \
      "$path" "$loc" "$warn_thresh"
    if [[ "$quiet" != "1" ]]; then
      printf 'check-file-loc: warn  %5d LOC  %s (> %d)\n' \
        "$loc" "$path" "$warn_thresh"
    fi
    warned=$((warned + 1))
  fi
done

printf 'check-file-loc: scanned=%d warned=%d failed=%d allowlisted=%d mode=%s\n' \
  "$scanned" "$warned" "$failed" "$allowlisted" "$mode"

# Stale-allowlist audit: an entry that matched nothing this run is
# dead weight. Fail loudly in enforce mode so a refactored file that
# no longer needs the exemption cannot silently keep it.
stale=0
for entry in "${!allow_exact[@]}"; do
  if [[ -z "${used_exact[$entry]:-}" ]]; then
    printf 'check-file-loc: stale allowlist entry (matched nothing): %s\n' "$entry"
    stale=$((stale + 1))
  fi
done
for pat in "${allow_globs[@]}"; do
  if [[ -z "${used_globs[$pat]:-}" ]]; then
    printf 'check-file-loc: stale allowlist pattern (matched nothing): %s\n' "$pat"
    stale=$((stale + 1))
  fi
done

if [[ "$mode" == "enforce" ]] && (( failed > 0 || stale > 0 )); then
  if (( failed > 0 )); then
    cat >&2 <<EOF

Split the offending file into a sub-package. See tracker #14 for the
architectural pattern (each variable axis becomes a folder; core/reporting/
is the reference implementation - datasources/ + formats/ + widgets/).
EOF
  fi
  exit 1
fi

exit 0
