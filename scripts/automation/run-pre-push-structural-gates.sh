#!/usr/bin/env bash
# Run the structural gate set required before a push.

set -uo pipefail

if [[ "${FDAI_STRUCTURAL_CACHE_ACTIVE:-0}" != "1" &&
      "${CI:-false}" != "true" && "${CI:-0}" != "1" &&
      "${GITHUB_ACTIONS:-false}" != "true" && "${GITHUB_ACTIONS:-0}" != "1" ]]; then
  exec python3 scripts/automation/local_validation_cache.py structural
fi

for gate_path in \
  scripts/quality/architecture/check-agents-imports.sh \
  scripts/quality/architecture/check-design-routes.py \
  scripts/quality/architecture/check-evaluation-boundaries.py \
  scripts/quality/architecture/check-fork-runtime-independence.py \
  scripts/quality/architecture/check-file-loc.sh \
  scripts/quality/architecture/check-independent-services.py \
  scripts/quality/architecture/check-operator-api-boundaries.py \
  scripts/quality/architecture/check-subsystem-fanout.sh \
  scripts/quality/architecture/check-venue-capability-contract.py \
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
    gate_command=(uv run --extra dev python "$gate_path")
  else
    gate_command=(bash "$gate_path")
  fi
  started=$SECONDS
  echo "structural-gates: gate=${gate} status=running"
  # Capture per process, not in a shared filename that parallel pushes overwrite.
  if output="$(CHECK_QUIET=1 timeout 600 "${gate_command[@]}" 2>&1)"; then
    echo "structural-gates: gate=${gate} status=0 duration=$((SECONDS - started))s"
  else
    echo "structural-gates: BLOCKED - ${gate} failed:" >&2
    printf '%s\n' "$output" | sed 's/^/  /' >&2
    exit 1
  fi
done

echo "structural-gates: OK"
