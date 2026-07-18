#!/usr/bin/env bash
#
# resume.sh - print a read-only snapshot of "where did I stop?"
#
# Companion to .github/prompts/resume-session.prompt.md. Answers the
# maintainer's most common start-of-session question ("what was I
# doing?") from local git + optional session-store artifacts, without
# touching the working tree.
#
# It prints, in order:
#   - current branch and last commit
#   - working-tree state (top 20 lines)
#   - unpushed commit count + subjects
#   - recent commit topics (last 10)
#   - unresolved TODO / FIXME added in the last week (if any)
#   - reminders about safe-edit rules
#
# Usage:
#   scripts/automation/resume.sh              # snapshot
#   scripts/automation/resume.sh --since 3d   # widen the recent-commit window
#
# Exit code: 0 always (report only), 2 on bad usage.

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

since="7d"
for arg in "$@"; do
    case "$arg" in
        --since=*) since="${arg#--since=}" ;;
        --since)
            echo "resume.sh: --since needs '=' form (e.g. --since=3d)" >&2
            exit 2
            ;;
        -h|--help)
            sed -n '2,22p' "$0"
            exit 0
            ;;
        *)
            echo "resume.sh: unknown argument '$arg'" >&2
            exit 2
            ;;
    esac
done

# Map a shorthand like "3d" or "1w" to a git --since string.
case "$since" in
    *d) since_git="${since%d} days ago" ;;
    *w) since_git="${since%w} weeks ago" ;;
    *h) since_git="${since%h} hours ago" ;;
    *)  since_git="$since" ;;
esac

hr() { printf '\n== %s ==\n' "$1" ; }

hr "git"
branch=$(git rev-parse --abbrev-ref HEAD)
last=$(git --no-pager log --oneline -1)
printf 'branch:      %s\n' "$branch"
printf 'last commit: %s\n' "$last"

hr "working tree"
tree=$(git status --short)
if [[ -z "$tree" ]]; then
    echo "clean"
else
    echo "$tree" | head -20
    total=$(echo "$tree" | wc -l | tr -d ' ')
    if (( total > 20 )); then
        printf '... (%d more)\n' "$((total - 20))"
    fi
fi

hr "unpushed"
if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    unpushed=$(git rev-list --count '@{u}..HEAD')
    printf '%s commits ahead of upstream\n' "$unpushed"
    if (( unpushed > 0 )); then
        git --no-pager log --oneline '@{u}..HEAD' | head -10
    fi
else
    echo "no upstream tracking configured"
fi

hr "recent commits (since $since_git)"
git --no-pager log --oneline --since="$since_git" | head -20

hr "recent TODO / FIXME (last $since)"
# Scan the diff on the branch for new TODO / FIXME markers introduced
# in the recent window. Fast heuristic; not exhaustive.
recent_marks=$(git --no-pager log --since="$since_git" -p --diff-filter=AM \
    -G'TODO|FIXME|XXX' -- 'src/**' 'docs/**' 'scripts/**' 2>/dev/null \
    | grep -E '^\+.*(TODO|FIXME|XXX)' | grep -vE '^\+\+\+' | head -10 || true)
if [[ -z "$recent_marks" ]]; then
    echo "(none)"
else
    echo "$recent_marks"
fi

hr "reminders"
cat <<'EOM'
- Use per-file `git add`; never `git add -A` while the tree is dirty.
- `git pull --rebase --autostash` before starting a fresh batch.
- Verify with `bash scripts/verify.sh --fast` before every commit.
- Push is a maintainer decision.
- See .github/prompts/resume-session.prompt.md for the full flow.
EOM
