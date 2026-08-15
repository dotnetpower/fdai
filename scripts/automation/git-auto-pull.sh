#!/usr/bin/env bash
# git-auto-pull.sh - periodically fetch and, when safe, rebase the current
# branch onto its remote. Backs the VS Code "git: auto-pull" background task
# so trunk-based (no-branch) collaboration stays conflict-light: everyone
# keeps their local `main` close to the remote instead of diverging.
#
# Safe by design: it NEVER rebases a dirty working tree or one that is
# mid-rebase - in those cases it only reports and waits, so it cannot
# clobber in-progress work. Only a clean tree that is strictly behind gets
# a `pull --rebase`.
#
# Interval (seconds) via FDAI_AUTOPULL_INTERVAL (default 180). A shorter interval
# detects remote drift sooner, which keeps rebases small and avoids rework that a
# late detection would force onto an already-validated local line.
set -uo pipefail

interval="${FDAI_AUTOPULL_INTERVAL:-180}"
toplevel="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
if [ -z "$toplevel" ]; then
  echo "[auto-pull] not a git repository; exiting."
  exit 0
fi
cd "$toplevel" || exit 0
git_common_dir="$(git rev-parse --git-common-dir 2>/dev/null || echo .git)"
if [[ "$git_common_dir" != /* ]]; then
  git_common_dir="$toplevel/$git_common_dir"
fi
validation_lock="$git_common_dir/fdai-validation-queue/lock"

echo "[auto-pull] watching '$toplevel' every ${interval}s (safe: clean tree only)."

while true; do
  branch="$(git symbolic-ref --short HEAD 2>/dev/null || echo "")"
  git_dir="$(git rev-parse --git-dir 2>/dev/null || echo .git)"
  if [ -z "$branch" ]; then
    :
  elif [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    echo "[auto-pull] working tree is dirty - skipping remote fetch."
  elif [ -d "$git_dir/rebase-merge" ] || [ -d "$git_dir/rebase-apply" ]; then
    echo "[auto-pull] rebase in progress - skipping remote fetch."
  elif [ -f "$validation_lock" ] && command -v flock >/dev/null 2>&1 \
    && ! flock -n "$validation_lock" -c true; then
    echo "[auto-pull] centralized validation is active - skipping remote fetch."
  elif git fetch --quiet origin "$branch" 2>/dev/null; then
    behind="$(git rev-list --count HEAD..FETCH_HEAD 2>/dev/null || echo 0)"
    ahead="$(git rev-list --count FETCH_HEAD..HEAD 2>/dev/null || echo 0)"
    if [ "$behind" -gt 0 ]; then
      if [ "$ahead" -gt 0 ]; then
        echo "[auto-pull] $branch has diverged ($ahead ahead, $behind behind) - skipping. Rebase manually after reviewing local commits."
      else
        echo "[auto-pull] $branch is $behind behind origin - pulling (rebase)..."
        if git pull --rebase --quiet origin "$branch"; then
          echo "[auto-pull] up to date."
        else
          echo "[auto-pull] pull --rebase failed - resolve manually (git status)."
        fi
      fi
    fi
  fi
  sleep "$interval"
done
