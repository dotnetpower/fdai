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
# Interval (seconds) via FDAI_AUTOPULL_INTERVAL (default 180).
set -uo pipefail

interval="${FDAI_AUTOPULL_INTERVAL:-180}"
toplevel="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
if [ -z "$toplevel" ]; then
  echo "[auto-pull] not a git repository; exiting."
  exit 0
fi
cd "$toplevel" || exit 0

echo "[auto-pull] watching '$toplevel' every ${interval}s (safe: clean tree only)."

while true; do
  branch="$(git symbolic-ref --short HEAD 2>/dev/null || echo "")"
  if [ -n "$branch" ] && git fetch --quiet origin "$branch" 2>/dev/null; then
    behind="$(git rev-list --count HEAD..FETCH_HEAD 2>/dev/null || echo 0)"
    if [ "$behind" -gt 0 ]; then
      git_dir="$(git rev-parse --git-dir 2>/dev/null || echo .git)"
      if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
        echo "[auto-pull] $branch is $behind behind origin, but the working tree is dirty - skipping. Commit or stash, then: git pull --rebase"
      elif [ -d "$git_dir/rebase-merge" ] || [ -d "$git_dir/rebase-apply" ]; then
        echo "[auto-pull] rebase in progress - skipping."
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
