#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

npm --prefix console test
# `npm exec` does not change directory, so the project path is resolved from the repository root.
npm --prefix console exec -- tsc --noEmit -p console/tsconfig.tests.json
npm --prefix console run build
npm --prefix cli test
npm --prefix cli run typecheck
