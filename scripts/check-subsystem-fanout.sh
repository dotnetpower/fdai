#!/usr/bin/env bash
#
# check-subsystem-fanout.sh - flag god-orchestrators inside src/fdai/core/
# before they reach control_loop.py scale (1,725 LOC / 30+ sibling
# subsystem imports).
#
# For each file under src/fdai/core/**, count how many *distinct*
# sibling core subsystems it imports from. A subsystem is the first
# path segment under core/ (e.g. `fdai.core.executor.xxx` counts as
# subsystem `executor`).
#
# Two thresholds:
#   * warn >= 8 distinct sibling subsystems
#   * fail >= 15
#
# Modes:
#   SUBSYSTEM_FANOUT_MODE=warn (default) - only warn, never fail
#   SUBSYSTEM_FANOUT_MODE=enforce        - warn + fail on >= FAIL
#
# Environment overrides (kept small on purpose):
#   SUBSYSTEM_FANOUT_WARN=8
#   SUBSYSTEM_FANOUT_FAIL=15
#
# Rationale: tracker issue #14 (issue #22). control_loop.py grew to
# import 30+ sibling subsystems and became a god-orchestrator; this
# script prevents the same pattern from re-emerging in the new
# core/pipeline/control_loop/orchestrator.py that G-2 will create,
# or anywhere else.
#
# Allowlist: scripts/.check-subsystem-fanout.allowlist (one path per
# line, '#' comments). Composition-style files that legitimately
# compose many subsystems (e.g. the orchestrator introduced by G-2)
# MUST be listed here with a written justification in the preceding
# comment. Public composition roots outside core/ do not need entries -
# they are not scanned.
#
# Regression: 2026-07-11 - added alongside check-file-loc.sh and
# check-agents-imports.sh as the three structural gates the tracker
# requires.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

warn_thresh="${SUBSYSTEM_FANOUT_WARN:-8}"
fail_thresh="${SUBSYSTEM_FANOUT_FAIL:-15}"
mode="${SUBSYSTEM_FANOUT_MODE:-warn}"

if ! [[ "$warn_thresh" =~ ^[0-9]+$ && "$fail_thresh" =~ ^[0-9]+$ ]]; then
  echo "check-subsystem-fanout: SUBSYSTEM_FANOUT_WARN/SUBSYSTEM_FANOUT_FAIL must be integers" >&2
  exit 2
fi
if (( warn_thresh >= fail_thresh )); then
  echo "check-subsystem-fanout: SUBSYSTEM_FANOUT_WARN ($warn_thresh) must be < SUBSYSTEM_FANOUT_FAIL ($fail_thresh)" >&2
  exit 2
fi

allowlist_file="scripts/.check-subsystem-fanout.allowlist"
declare -A allowlist=()
if [[ -f "$allowlist_file" ]]; then
  while IFS= read -r line; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    allowlist["$line"]=1
  done < "$allowlist_file"
fi

mapfile -t files < <(
  find src/fdai/core -type f -name '*.py' \
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
  echo "check-subsystem-fanout: no core/ Python files - skipping."
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

  # Derive this file's own subsystem so self-imports don't inflate the fan-out.
  # 'src/fdai/core/<subsystem>/...' or 'src/fdai/core/<subsystem>.py'.
  own=""
  rel="${path#src/fdai/core/}"
  case "$rel" in
    */*) own="${rel%%/*}" ;;
    *.py) own="${rel%.py}" ;;
  esac

  # Match `from fdai.core.X` and `import fdai.core.X`; capture X.
  # -h suppresses filenames, -o prints only the match. Every grep in
  # this pipe returns 1 on zero hits; wrap with `|| true` under
  # `set -o pipefail` or a no-match kills the whole script.
  subs=$(
    { grep -hEo '(from|import)[[:space:]]+fdai\.core\.[A-Za-z_][A-Za-z0-9_]*' \
             "$path" 2>/dev/null \
        | sed -E 's/(from|import)[[:space:]]+fdai\.core\.//' \
        | { grep -v -x "$own" || true; } \
        | LC_ALL=C sort -u ; } || true
  )
  if [[ -z "$subs" ]]; then
    count=0
  else
    count=$(printf '%s\n' "$subs" | wc -l)
  fi

  scanned=$((scanned + 1))

  if (( count >= fail_thresh )); then
    printf '::warning file=%s,line=1::check-subsystem-fanout: %d sibling subsystems (>= fail %d)\n' \
      "$path" "$count" "$fail_thresh"
    printf 'check-subsystem-fanout: FAIL  %3d subs  %s (>= %d)\n' \
      "$count" "$path" "$fail_thresh"
    printf '%s\n' "$subs" | sed 's/^/                                  - /'
    failed=$((failed + 1))
  elif (( count >= warn_thresh )); then
    printf '::notice file=%s,line=1::check-subsystem-fanout: %d sibling subsystems (>= warn %d)\n' \
      "$path" "$count" "$warn_thresh"
    printf 'check-subsystem-fanout: warn  %3d subs  %s (>= %d)\n' \
      "$count" "$path" "$warn_thresh"
    warned=$((warned + 1))
  fi
done

printf 'check-subsystem-fanout: scanned=%d warned=%d failed=%d allowlisted=%d mode=%s\n' \
  "$scanned" "$warned" "$failed" "$allowlisted" "$mode"

if [[ "$mode" == "enforce" ]] && (( failed > 0 )); then
  cat >&2 <<EOF

Extract stages behind a Protocol (see G-2 in tracker #14) so this file
composes a small list instead of hard-wiring every subsystem. If this
file is a legitimate composition root, add it to
$allowlist_file with a one-line justification in the preceding comment.
EOF
  exit 1
fi

exit 0
