#!/usr/bin/env bash
# Run the structural gate set required before a push.

set -uo pipefail

if [[ "${FDAI_STRUCTURAL_CACHE_ACTIVE:-0}" != "1" &&
      "${CI:-false}" != "true" && "${CI:-0}" != "1" &&
      "${GITHUB_ACTIONS:-false}" != "true" && "${GITHUB_ACTIONS:-0}" != "1" ]]; then
  exec python3 scripts/automation/local_validation_cache.py structural
fi

gates=(
  scripts/quality/architecture/check-agents-imports.sh
  scripts/quality/architecture/check-action-type-runtime-support.py
  scripts/quality/architecture/check-design-routes.py
  scripts/quality/architecture/check-evaluation-boundaries.py
  scripts/quality/architecture/check-fork-runtime-independence.py
  scripts/quality/architecture/check-file-loc.sh
  scripts/quality/architecture/check-independent-services.py
  scripts/quality/architecture/check-operator-api-boundaries.py
  scripts/quality/architecture/check-subsystem-fanout.sh
  scripts/quality/architecture/check-venue-capability-contract.py
  scripts/quality/repository/check-doc-links.sh
)

gate_name() {
  local name="${1##*/}"
  printf '%s' "${name%.sh}"
}

for gate_path in "${gates[@]}"; do
  if [[ ! -f "$gate_path" ]]; then
    echo "structural-gates: BLOCKED - required gate is missing: $gate_path" >&2
    exit 1
  fi
  if [[ "$gate_path" == *.py ]] && ! command -v uv >/dev/null 2>&1; then
    echo "structural-gates: BLOCKED - uv is required for project-version Python gates." >&2
    exit 1
  fi
done

# The gates are independent read-only checks, so run them concurrently: serially they took 81 s
# of a 116 s push, and the slowest single gate takes about 32 s.
cpus="$(nproc 2>/dev/null || echo 4)"
limit="${FDAI_STRUCTURAL_JOBS:-$((cpus < 6 ? cpus : 6))}"
results="$(mktemp -d)"
trap 'rm -rf "$results"' EXIT

run_gate() {
  local gate_path="$1" gate started code
  local -a gate_command
  gate="$(gate_name "$gate_path")"
  if [[ "$gate_path" == *.py ]]; then
    gate_command=(uv run --extra dev python "$gate_path")
  else
    gate_command=(bash "$gate_path")
  fi
  started=$SECONDS
  echo "structural-gates: gate=${gate} status=running"
  # Capture per gate, not in a shared filename that parallel pushes overwrite.
  CHECK_QUIET=1 timeout 600 "${gate_command[@]}" >"$results/$gate.out" 2>&1
  code=$?
  printf '%s %s\n' "$code" "$((SECONDS - started))" >"$results/$gate.status"
}

for gate_path in "${gates[@]}"; do
  while (($(jobs -rp | wc -l) >= limit)); do
    wait -n || true
  done
  run_gate "$gate_path" &
done
wait

failed=0
for gate_path in "${gates[@]}"; do
  gate="$(gate_name "$gate_path")"
  read -r code duration <"$results/$gate.status" || { code=1; duration=0; }
  if ((code == 0)); then
    echo "structural-gates: gate=${gate} status=0 duration=${duration}s"
  else
    echo "structural-gates: BLOCKED - ${gate} failed:" >&2
    sed 's/^/  /' "$results/$gate.out" >&2
    failed=1
  fi
done
((failed == 0)) || exit 1

echo "structural-gates: OK"
