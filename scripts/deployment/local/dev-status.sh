#!/usr/bin/env bash
#
# dev-status.sh - one-shot health check for parallel FDAI sessions.
#
# Prints a compact snapshot of what matters when the maintainer runs
# multiple sessions against the same repo (see the gotcha logged in
# /memories/repo/coding-ability.md):
#
#   - which git branch + last commit
#   - working-tree state (uncommitted work you MUST NOT step on)
#   - unpushed commits count
#   - what the fast gates would say right now
#   - which Azure subscription each az CLI profile is on (default +
#     the customer profile at $HOME/.azure-customer, if present)
#
# Usage:
#   scripts/deployment/local/dev-status.sh          # snapshot
#   scripts/deployment/local/dev-status.sh --gates  # also run the fast gate suite
#
# Exit code: 0 always (report only), 2 on bad usage.

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

run_gates=0
for arg in "$@"; do
    case "$arg" in
        --gates) run_gates=1 ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *) echo "dev-status.sh: unknown argument '$arg'" >&2 ; exit 2 ;;
    esac
done

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

hr "azure profiles"
if command -v az >/dev/null 2>&1; then
    default_show=$(env -u AZURE_CONFIG_DIR az account show \
        --query "{sub:name, id:id, tenant:tenantId, user:user.name}" \
        -o tsv 2>/dev/null || true)
    if [[ -n "$default_show" ]]; then
        printf 'default (~/.azure):    %s\n' "$default_show"
    else
        printf 'default (~/.azure):    not logged in\n'
    fi
    if [[ -d "$HOME/.azure-customer" ]]; then
        cust_show=$(AZURE_CONFIG_DIR="$HOME/.azure-customer" az account show \
            --query "{sub:name, id:id, tenant:tenantId, user:user.name}" \
            -o tsv 2>/dev/null || true)
        if [[ -n "$cust_show" ]]; then
            printf 'customer (.azure-customer): %s\n' "$cust_show"
        else
            printf 'customer (.azure-customer): not logged in\n'
        fi
    fi
else
    echo "az CLI not on PATH"
fi

if [[ $run_gates -eq 1 ]]; then
    hr "fast gates"
    bash scripts/verify.sh --fast || true
fi

hr "reminders"
cat <<'EOM'
- Use per-file `git add`; never `git add -A` while the tree is dirty.
- `git pull --rebase --autostash` before starting a fresh batch.
- Push is a maintainer decision.
EOM
