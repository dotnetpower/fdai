#!/usr/bin/env bash
#
# check-english-only.sh - enforce the English-only rule outside the
# -ko.md translation carve-out.
#
# Rules (see .github/instructions/language.instructions.md):
#   1. All code, config, comments, identifiers, commits, tests, fixtures,
#      logs, error strings and .github/** are English-only.
#   2. The ONLY committed non-English text lives in `foo-ko.md` sibling
#      files under `README.md` (root) and `docs/**/*.md`.
#   3. Everything else with Hangul (U+AC00-U+D7A3 or U+1100-U+11FF) or
#      CJK Unified Ideographs (U+4E00-U+9FFF) fails this check.
#
# Scope (included by default):
#   Every git-tracked file EXCEPT:
#     * *-ko.md (translation carve-out)
#     * mocks/**, examples/** (design mock-ups, not shipped code)
#     * binary assets (png/jpg/jpeg/gif/webp/pdf/ico/woff/woff2/ttf/otf)
#     * uv.lock (hash-only content; guaranteed ASCII, exclude to speed up)
#
# Justified allowlist (legitimately non-English, each with a reason):
#     * site/src/content/docs/ko/**            Korean locale presentation;
#                                              every file is a mount of an
#                                              already-carved-out -ko.md source.
#     * .github/skills/documentation-writing/SKILL.md
#                                              teaches Korean translation tone;
#                                              its Korean examples are quoted data.
#     * scripts/apply-tone-corrections.py      Korean tone-correction data tables.
#     * tools/baseline_run.py                  emits a localized Korean report.
#     * site/src/components/StaleTranslationBanner.astro
#                                              banner rendered only on Korean pages.
#
# Exit codes: 0 on success, 1 on any violation.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

# Enumerate every file that would end up in the tree (tracked + untracked
# but not gitignored), then filter out excluded paths.
mapfile -t files < <(
  git ls-files -co --exclude-standard \
    ':(exclude)*-ko.md' \
    ':(exclude)mocks/**' \
    ':(exclude)examples/**' \
    ':(exclude)site/src/content/docs/ko/**' \
    ':(exclude).github/skills/documentation-writing/SKILL.md' \
    ':(exclude)scripts/apply-tone-corrections.py' \
    ':(exclude)tools/baseline_run.py' \
    ':(exclude)site/src/components/StaleTranslationBanner.astro' \
    ':(exclude)*.png' \
    ':(exclude)*.jpg' \
    ':(exclude)*.jpeg' \
    ':(exclude)*.gif' \
    ':(exclude)*.webp' \
    ':(exclude)*.pdf' \
    ':(exclude)*.ico' \
    ':(exclude)*.woff' \
    ':(exclude)*.woff2' \
    ':(exclude)*.ttf' \
    ':(exclude)*.otf' \
    ':(exclude)uv.lock' \
    | sort -u
)

errors=0
for f in "${files[@]}"; do
  [[ -f "$f" ]] || continue

  # Hangul (Syllables + Jamo) OR CJK Unified Ideographs.
  # Using a Perl-compatible regex via grep -P so we can match \x{...}.
  # NOTE: -P must not be combined with -E (grep rejects conflicting
  # matchers, which silently made this gate a no-op before the fix).
  if grep -Pn '[\x{AC00}-\x{D7A3}\x{1100}-\x{11FF}\x{4E00}-\x{9FFF}]' "$f" >/dev/null 2>&1; then
    echo "check-english-only: $f contains non-ASCII natural-language characters" >&2
    grep -Pn '[\x{AC00}-\x{D7A3}\x{1100}-\x{11FF}\x{4E00}-\x{9FFF}]' "$f" | head -5 | sed 's/^/    /' >&2
    errors=$((errors + 1))
  fi
done

if (( errors > 0 )); then
  echo "check-english-only: FAILED with ${errors} file(s) outside the -ko.md carve-out." >&2
  echo "Fix: move the non-English text to the sibling -ko.md file, or remove it." >&2
  exit 1
fi

printf 'check-english-only: OK (%d tracked file(s) scanned)\n' "${#files[@]}"
