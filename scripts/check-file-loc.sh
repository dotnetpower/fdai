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
# exempt in a comment on the preceding line, matching the convention in
# scripts/check-english-only.sh. An allowlisted file is skipped entirely.
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

allowlist_file="scripts/.check-file-loc.allowlist"
declare -A allowlist=()
if [[ -f "$allowlist_file" ]]; then
  while IFS= read -r line; do
    # Strip comments and whitespace; skip blanks.
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    allowlist["$line"]=1
  done < "$allowlist_file"
fi

# Deterministic ordering; excludes __pycache__ automatically.
mapfile -t files < <(
  find src/fdai -type f -name '*.py' \
    ! -path '*/__pycache__/*' \
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
  if [[ -n "${allowlist[$path]:-}" ]]; then
    allowlisted=$((allowlisted + 1))
    continue
  fi
  scanned=$((scanned + 1))
  loc=$(wc -l < "$path")
  if (( loc > fail_thresh )); then
    # GitHub Actions annotation so PR Files tab highlights the file.
    printf '::warning file=%s,line=1::check-file-loc: %d LOC exceeds fail threshold %d\n' \
      "$path" "$loc" "$fail_thresh"
    printf 'check-file-loc: FAIL  %5d LOC  %s (> %d)\n' \
      "$loc" "$path" "$fail_thresh"
    failed=$((failed + 1))
  elif (( loc > warn_thresh )); then
    printf '::notice file=%s,line=1::check-file-loc: %d LOC exceeds warn threshold %d\n' \
      "$path" "$loc" "$warn_thresh"
    printf 'check-file-loc: warn  %5d LOC  %s (> %d)\n' \
      "$loc" "$path" "$warn_thresh"
    warned=$((warned + 1))
  fi
done

printf 'check-file-loc: scanned=%d warned=%d failed=%d allowlisted=%d mode=%s\n' \
  "$scanned" "$warned" "$failed" "$allowlisted" "$mode"

if [[ "$mode" == "enforce" ]] && (( failed > 0 )); then
  cat >&2 <<EOF

Split the offending file into a sub-package. See tracker #14 for the
architectural pattern (each variable axis becomes a folder; core/reporting/
is the reference implementation - datasources/ + formats/ + widgets/).
EOF
  exit 1
fi

exit 0
