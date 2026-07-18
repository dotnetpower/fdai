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
#
# Auto-fix: run `python3 scripts/quality/localization/normalize-punctuation.py` (for markdown, with
# code-fence protection) or add `--whole-file` for source files where the whole
# content is code.
#
# Exit codes: 0 on success, 1 on any violation.

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

pattern='[\x{2014}\x{2013}\x{2026}\x{201C}\x{201D}\x{2018}\x{2019}\x{00A0}]'

errors=0
for f in "${files[@]}"; do
  [[ -f "$f" ]] || continue
  if grep -PnE "$pattern" "$f" >/dev/null 2>&1; then
    echo "check-punctuation: $f contains disallowed non-ASCII typography" >&2
    grep -PnE "$pattern" "$f" | head -5 | sed 's/^/    /' >&2
    errors=$((errors + 1))
  fi
done

if (( errors > 0 )); then
  echo "check-punctuation: FAILED (${errors} file(s))." >&2
  echo "Fix: run 'python3 scripts/quality/localization/normalize-punctuation.py' to auto-normalize." >&2
  exit 1
fi

printf 'check-punctuation: OK (%d tracked file(s) scanned)\n' "${#files[@]}"
