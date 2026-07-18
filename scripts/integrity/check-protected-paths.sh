#!/usr/bin/env bash
#
# check-protected-paths.sh - warn (upstream) or block (fork) when a change
# touches the FRAMEWORK SURFACE.
#
# FDAI is both a solution AND a framework. The framework surface is the set
# of files a downstream fork MUST NOT edit (it customizes by dependency
# injection at a composition root instead - see
# docs/roadmap/fork-and-sequencing/downstream-fork-guide.md § 3 "The one hard rule"). In the
# upstream repo itself these files ARE edited - that is how the framework
# evolves - so this guard is deliberately mode-aware:
#
#   * FORK mode      -> HARD BLOCK (exit 1). A fork must never edit these.
#   * UPSTREAM mode  -> ADVISORY WARNING (exit 0). Framework maintainers are
#                       told they are changing a contract other people build
#                       on, and CODEOWNERS forces an owner review; the push /
#                       CI is not blocked.
#
# Mode detection (first match wins):
#   1. FDAI_FORK=1 in the environment, OR
#   2. a `.fdai-fork` marker file at the repo root, OR
#   3. `git config --bool fdai.fork` == true
# Otherwise the repo is treated as UPSTREAM.
#
# Usage:
#   scripts/integrity/check-protected-paths.sh [<git-range>]
#     <git-range>   optional; e.g. "origin/main...HEAD" or "FETCH_HEAD..HEAD".
#                   When omitted the script compares against origin/main, then
#                   falls back to the working tree vs HEAD.
#
# In GitHub Actions (GITHUB_ACTIONS=true) each hit is also emitted as a
# `::warning file=...::` annotation so it surfaces on the PR "Files changed"
# tab even in upstream (advisory) mode.
#
# Exit codes: 0 = clean or advisory-only (upstream); 1 = blocked (fork).

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || echo ".")"
cd "$repo_root"

# ---------------------------------------------------------------------------
# The framework surface. Prefix-matched against each changed path (repo-root
# relative). The list is loaded from the single source of truth
# scripts/lib/framework-surface.txt (shared with the integrity manifest tools)
# so the guard and the signed manifest can never drift apart.
# ---------------------------------------------------------------------------
surface_list="$repo_root/scripts/lib/framework-surface.txt"
if [ ! -f "$surface_list" ]; then
  echo "check-protected-paths: ERROR - missing $surface_list (the framework-surface list)." >&2
  exit 2
fi
protected_prefixes=()
while IFS= read -r line; do
  line="${line%%#*}"                       # strip inline/full-line comments
  line="$(printf '%s' "$line" | tr -d '[:space:]')"
  [ -n "$line" ] && protected_prefixes+=("$line")
done < "$surface_list"
if [ "${#protected_prefixes[@]}" -eq 0 ]; then
  echo "check-protected-paths: ERROR - $surface_list is empty after parsing." >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# Mode detection.
# ---------------------------------------------------------------------------
mode="upstream"
if [ "${FDAI_FORK:-0}" = "1" ]; then
  mode="fork"
elif [ -f "$repo_root/.fdai-fork" ]; then
  mode="fork"
elif [ "$(git config --bool fdai.fork 2>/dev/null || echo false)" = "true" ]; then
  mode="fork"
fi

# ---------------------------------------------------------------------------
# Resolve the diff spec. A caller (pre-push hook / CI) passes an explicit
# range; a manual no-arg run derives the default remote branch instead of
# hardcoding `origin/main` (a fork may default to `fork/main`).
# ---------------------------------------------------------------------------
range="${1:-}"
if [ -n "$range" ]; then
  diff_spec="$range"
else
  default_ref="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  if [ -z "$default_ref" ] && git rev-parse --verify --quiet origin/main >/dev/null 2>&1; then
    default_ref="origin/main"
  fi
  if [ -n "$default_ref" ]; then
    diff_spec="${default_ref}...HEAD"
  else
    # No remote base known: inspect working tree + staged vs last commit.
    diff_spec="HEAD"
  fi
fi

# Fail LOUD (exit 2), never silently pass, when the diff cannot be computed -
# an unresolved base ref must not look like "no protected files changed".
diff_out="$(git diff --name-only --diff-filter=d "$diff_spec" 2>&1)"
rc=$?
if [ "$rc" -ne 0 ]; then
  {
    echo "check-protected-paths: ERROR - cannot compute diff for '$diff_spec' (mode=$mode)."
    echo "  git said: $diff_out"
    echo "  A caller MUST pass a resolvable range (e.g. 'BASE...HEAD'). Refusing to"
    echo "  pass silently, because that would hide a framework-surface edit."
  } >&2
  exit 2
fi
mapfile -t changed < <(printf '%s\n' "$diff_out" | grep -v '^[[:space:]]*$' || true)

if [ "${#changed[@]}" -eq 0 ]; then
  echo "check-protected-paths: no changed files to inspect (mode=$mode)."
  exit 0
fi

# ---------------------------------------------------------------------------
# Match changed files against the framework surface. An entry ending in '/'
# is a directory prefix; any other entry is matched EXACTLY (so the
# `composition.py` file entry never matches `composition.py.bak`).
# ---------------------------------------------------------------------------
_is_protected() {
  local f="$1" p
  for p in "${protected_prefixes[@]}"; do
    case "$p" in
      */) case "$f" in "$p"*) return 0 ;; esac ;;
      *) [ "$f" = "$p" ] && return 0 ;;
    esac
  done
  return 1
}

hits=()
for f in "${changed[@]}"; do
  if _is_protected "$f"; then
    hits+=("$f")
  fi
done

if [ "${#hits[@]}" -eq 0 ]; then
  echo "check-protected-paths: OK - no framework-surface files touched (mode=$mode)."
  exit 0
fi

# GitHub Actions annotations (surface on the PR Files tab in both modes).
if [ "${GITHUB_ACTIONS:-false}" = "true" ]; then
  for f in "${hits[@]}"; do
    echo "::warning file=${f}::Framework-surface file changed. A fork MUST NOT edit this; see docs/roadmap/fork-and-sequencing/downstream-fork-guide.md."
  done
fi

if [ "$mode" = "fork" ]; then
  {
    echo ""
    echo "=============================================================="
    echo " BLOCKED - fork edited the framework surface"
    echo "=============================================================="
    printf '  %s\n' "${hits[@]}"
    echo ""
    echo "A downstream fork MUST NOT edit these files. Customize by"
    echo "dependency injection at your own composition root instead:"
    echo "  - wrap fdai.composition.default_container() and use"
    echo "    dataclasses.replace() to swap the seams you own, or"
    echo "  - add catalog entries / adapters under fork/, not here."
    echo ""
    echo "See docs/roadmap/fork-and-sequencing/downstream-fork-guide.md § 3 (the one hard rule)."
    echo "If this is a genuine upstream gap, open an upstream issue."
    echo ""
    echo "Local-only override (audited by review): FDAI_ALLOW_PROTECTED=1"
  } >&2
  if [ "${FDAI_ALLOW_PROTECTED:-0}" = "1" ]; then
    if [ "${GITHUB_ACTIONS:-false}" = "true" ]; then
      # A fork MUST NOT be able to defeat its own merge gate with a CI
      # variable. The override is a local convenience only.
      echo "check-protected-paths: FDAI_ALLOW_PROTECTED is IGNORED in CI - still blocking." >&2
    else
      echo "check-protected-paths: local override in effect (FDAI_ALLOW_PROTECTED=1) - not blocking." >&2
      exit 0
    fi
  fi
  exit 1
fi

# Upstream: advisory only.
{
  echo ""
  echo "--------------------------------------------------------------"
  echo " NOTICE - you changed the FRAMEWORK SURFACE (upstream mode)"
  echo "--------------------------------------------------------------"
  printf '  %s\n' "${hits[@]}"
  echo ""
  echo "These files are a contract downstream forks build on and MUST"
  echo "NOT edit. Editing them upstream is legitimate, but:"
  echo "  - keep the change backward-compatible within a major version,"
  echo "  - a Protocol-signature change is a BREAKING change (ship the"
  echo "    new seam alongside the old for one release), and"
  echo "  - CODEOWNERS will request an owner review."
  echo ""
  echo "See docs/roadmap/fork-and-sequencing/downstream-fork-guide.md § 6.1 (version pinning)."
} >&2
exit 0
