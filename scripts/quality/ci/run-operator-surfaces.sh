#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

npm --prefix console test
npm --prefix console run build
npm --prefix cli test
npm --prefix cli run typecheck
