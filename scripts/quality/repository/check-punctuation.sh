#!/usr/bin/env bash
#
# check-punctuation.sh - block non-ASCII typography that violates our
# coding-conventions rule (see .github/instructions/language.instructions.md
# and coding-conventions.instructions.md):
#
#   Prefer plain ASCII punctuation (-, ", ') over smart quotes and em-dashes.
#
# Blocked characters (in any tracked text file):
#   U+2014 EM DASH           (--)
#   U+2013 EN DASH           (--)
#   U+2026 HORIZONTAL ELLIPSIS
#   U+201C / U+201D          smart double quotes
#   U+2018 / U+2019          smart single quotes
#   U+00A0                   no-break space (invisible, breaks grep/diff)
#
# Scope: every git-tracked file except binary assets and vendored bundles.
# When paths are provided, only those staged-file candidates are checked.
#
# Auto-fix: run `python3 scripts/quality/localization/normalize-punctuation.py` (for markdown, with
# code-fence protection) or add `--whole-file` for source files where the whole
# content is code.
#
# Exit codes: 0 on success, 1 on any violation.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if (( $# > 0 )); then
  files=()
  for file in "$@"; do
    case "$file" in
      *.png|*.jpg|*.jpeg|*.gif|*.webp|*.svg|*.pdf|*.ico|*.woff|*.woff2|*.ttf|*.otf|uv.lock|*.jsonl) ;;
      *) [[ -f "$file" ]] && files+=("$file") ;;
    esac
  done
else
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
fi

if (( ${#files[@]} == 0 )); then
  echo "check-punctuation: OK (no text files to scan)"
  exit 0
fi

pattern='[\x{2014}\x{2013}\x{2026}\x{201C}\x{201D}\x{2018}\x{2019}\x{00A0}]'
baseline_path="scripts/quality/repository/punctuation-baseline.txt"
declare -A baseline_sha=()
if [[ -f "$baseline_path" ]]; then
  while read -r sha path || [[ -n "$sha" || -n "$path" ]]; do
    [[ -n "$sha" && -n "$path" ]] && baseline_sha["$path"]="$sha"
  done < "$baseline_path"
fi

errors=0
grandfathered=0
hits=""
if hits="$(LC_ALL=C.UTF-8 LANG=C.UTF-8 grep -PnH "$pattern" "${files[@]}" 2>&1)"; then
  mapfile -t violating_files < <(printf '%s\n' "$hits" | cut -d: -f1 | sort -u)
  for file in "${violating_files[@]}"; do
    current_sha="$(git hash-object "$file")"
    if [[ "${baseline_sha[$file]:-}" == "$current_sha" ]]; then
      grandfathered=$((grandfathered + 1))
      continue
    fi
    echo "check-punctuation: $file contains disallowed non-ASCII typography" >&2
    printf '%s\n' "$hits" | grep -F "$file:" | head -5 | sed 's/^/    /' >&2 || true
    errors=$((errors + 1))
  done
else
  grep_status=$?
  if (( grep_status != 1 )); then
    echo "check-punctuation: scanner failed: $hits" >&2
    exit "$grep_status"
  fi
fi

if (( errors > 0 )); then
  echo "check-punctuation: FAILED (${errors} file(s))." >&2
  echo "Fix: run 'python3 scripts/quality/localization/normalize-punctuation.py' to auto-normalize." >&2
  exit 1
fi

printf 'check-punctuation: OK (%d file(s) scanned, %d baseline blob(s) unchanged)\n' \
  "${#files[@]}" "$grandfathered"
