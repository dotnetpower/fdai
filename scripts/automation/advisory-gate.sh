#!/usr/bin/env bash
# Run one documentation-coupled gate as advice for a local work-in-progress commit.
#
# Owning-doc impact, English/Korean sync, Korean prose quality, and derived-source pins
# stay enforced for the pushed range by .githooks/pre-push and by CI (scripts/verify.sh),
# so a failing result here reports the gap without blocking the commit.
set -uo pipefail

if [ "$#" -eq 0 ]; then
  echo "advisory-gate: usage: advisory-gate.sh <command> [args...]" >&2
  exit 2
fi

if "$@"; then
  exit 0
fi
echo "pre-commit: ADVISORY - '$1 ${2:-}' reported a gap; pre-push and CI enforce it for the pushed range." >&2
exit 0
