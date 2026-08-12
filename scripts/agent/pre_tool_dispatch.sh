#!/usr/bin/env bash
set -euo pipefail

payload="$(cat)"
case "$payload" in
  *apply_patch*|*create_file*|*read_file*|*run_in_terminal*|*runTests*|*parallel*)
    printf '%s' "$payload" | python3 -S -m scripts.agent.pre_tool_dispatch
    ;;
  *)
    printf '{"continue":true}\n'
    ;;
esac
