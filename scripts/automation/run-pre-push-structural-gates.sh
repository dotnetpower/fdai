#!/usr/bin/env bash
# Run the structural gate set required before a push.

set -uo pipefail

for gate_path in \
  scripts/quality/architecture/check-agents-imports.sh \
  scripts/quality/architecture/check-design-routes.py \
  scripts/quality/architecture/check-evaluation-boundaries.py \
  scripts/quality/architecture/check-fork-runtime-independence.py \
  scripts/quality/architecture/check-file-loc.sh \
  scripts/quality/architecture/check-independent-services.py \
  scripts/quality/architecture/check-operator-api-boundaries.py \
  scripts/quality/architecture/check-subsystem-fanout.sh \
  scripts/quality/repository/check-doc-links.sh
do
  gate="${gate_path##*/}"
  gate="${gate%.sh}"
  if [[ ! -f "$gate_path" ]]; then
    echo "structural-gates: BLOCKED - required gate is missing: $gate_path" >&2
    exit 1
  fi
  if [[ "$gate_path" == *.py ]]; then
    if ! command -v uv >/dev/null 2>&1; then
      echo "structural-gates: BLOCKED - uv is required for project-version Python gates." >&2
      exit 1
    fi
    gate_command=(uv run python "$gate_path")
  else
    gate_command=(bash "$gate_path")
  fi
  output="${TMPDIR:-/tmp}/pre-push-${gate}.out"
  if ! CHECK_QUIET=1 "${gate_command[@]}" > "$output" 2>&1; then
    echo "structural-gates: BLOCKED - ${gate} failed:" >&2
    sed 's/^/  /' "$output" >&2
    exit 1
  fi
done

echo "structural-gates: OK"
