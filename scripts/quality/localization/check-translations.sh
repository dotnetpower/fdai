#!/usr/bin/env bash
#
# check-translations.sh - enforce the .md + -ko.md pair rule.
#
# Rules (see .github/instructions/language.instructions.md):
#   1. Every in-scope English `foo.md` MUST have a sibling `foo-ko.md`.
#   2. Every `foo-ko.md` MUST carry YAML front-matter with `translation_of`
#      and `translation_source_sha` fields.
#   3. The recorded `translation_source_sha` MUST equal `git hash-object foo.md`
#      of the current working-tree source; a mismatch means the translation is
#      stale relative to a change in the English canonical.
#   4. `-ko.md` files with no matching English source are forbidden.
#
# Scope:
#   Included: root README.md, everything under docs/**/*.md
#   Excluded: .github/**, docs/internals/** (English-only internal engineering
#             notes, like .github/**), mocks/**, examples/**, node_modules/**,
#             site/**
#
# Exit codes: 0 on success, 1 on any violation.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

errors=0
report() { echo "check-translations: $*" >&2; errors=$((errors + 1)); }

# Enumerate in-scope English markdown files (canonical sources).
mapfile -t english_docs < <(
  { echo "README.md"; find docs -type f -name '*.md' 2>/dev/null; } \
    | grep -Ev '(^|/)[^/]+-ko\.md$' \
    | grep -Ev '^docs/internals/' \
    | sort -u
)

# Enumerate all -ko.md files (to catch orphans).
mapfile -t korean_docs < <(
  find . -type f -name '*-ko.md' \
    -not -path './.github/*' \
    -not -path './mocks/*' \
    -not -path './examples/*' \
    -not -path './node_modules/*' \
    -not -path './site/node_modules/*' \
    -not -path './.git/*' \
    | sed 's|^\./||' \
    | sort -u
)

# Rule 1 + 2 + 3: every English doc has a valid, up-to-date -ko.md.
for src in "${english_docs[@]}"; do
  ko="${src%.md}-ko.md"
  if [[ ! -f "$ko" ]]; then
    report "missing translation: $ko (English source: $src)"
    continue
  fi

  # Extract front-matter (between the first pair of --- lines at file start).
  fm="$(awk 'BEGIN{n=0} /^---$/{n++; if(n==2) exit; next} n==1{print}' "$ko")"
  if [[ -z "$fm" ]]; then
    report "$ko: missing YAML front-matter (need translation_of + translation_source_sha)"
    continue
  fi

  translation_of="$(printf '%s\n' "$fm" | awk -F': *' '$1=="translation_of"{print $2; exit}' | tr -d '"'"'")"
  recorded_sha="$(printf '%s\n' "$fm" | awk -F': *' '$1=="translation_source_sha"{print $2; exit}' | tr -d '"'"'")"

  if [[ -z "$translation_of" ]]; then
    report "$ko: front-matter missing translation_of"
  fi
  if [[ -z "$recorded_sha" ]]; then
    report "$ko: front-matter missing translation_source_sha"
    continue
  fi

  # translation_of should be the basename of the English source (siblings only).
  src_base="$(basename "$src")"
  if [[ -n "$translation_of" && "$translation_of" != "$src_base" ]]; then
    report "$ko: translation_of='$translation_of' does not match sibling English file '$src_base'"
  fi

  current_sha="$(git hash-object "$src")"
  if [[ "$recorded_sha" != "$current_sha" ]]; then
    report "$ko: stale translation. recorded_sha=$recorded_sha, current sha of $src=$current_sha. Update the translation and refresh translation_source_sha."
  fi
done

# Rule 4: no orphan -ko.md files (without an English sibling in scope).
for ko in "${korean_docs[@]}"; do
  src="${ko%-ko.md}.md"
  if [[ ! -f "$src" ]]; then
    report "orphan translation: $ko has no English source $src"
    continue
  fi
  # Also verify orphan is inside the allowed scope (root README or docs/**).
  case "$ko" in
    README-ko.md|docs/*) ;;
    *) report "out-of-scope translation file: $ko (only root README-ko.md and docs/**/-ko.md are allowed)" ;;
  esac
done

if (( errors > 0 )); then
  echo "check-translations: FAILED with $errors violation(s)." >&2
  exit 1
fi

printf 'check-translations: OK (%d English docs, %d translations verified)\n' \
  "${#english_docs[@]}" "${#korean_docs[@]}"
