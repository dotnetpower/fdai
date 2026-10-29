#!/usr/bin/env bash
# Run the structural gate set required before a push.

set -uo pipefail

cpus="$(nproc 2>/dev/null || echo 4)"
limit="${FDAI_STRUCTURAL_JOBS-$((cpus < 6 ? cpus : 6))}"
total_timeout="${FDAI_STRUCTURAL_TIMEOUT_SECONDS-600}"
if [[ ! "$limit" =~ ^[1-9][0-9]?$ ]] || ((limit > 64)); then
  echo "structural-gates: BLOCKED - FDAI_STRUCTURAL_JOBS must be an integer from 1 to 64." >&2
  exit 125
fi
if [[ ! "$total_timeout" =~ ^[1-9][0-9]{0,3}$ ]] || ((total_timeout > 3600)); then
  echo "structural-gates: BLOCKED - FDAI_STRUCTURAL_TIMEOUT_SECONDS must be an integer from 1 to 3600." >&2
  exit 125
fi

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

for utility in setsid timeout; do
  if ! command -v "$utility" >/dev/null 2>&1; then
    echo "structural-gates: BLOCKED - required utility is missing: $utility" >&2
    exit 125
  fi
done

results="$PWD/.fdai-structural-gates.${BASHPID}.${RANDOM}"
if ! (umask 077; mkdir -- "$results"); then
  echo "structural-gates: BLOCKED - cannot create isolated gate results." >&2
  exit 125
fi
active=()

cleanup() {
  local code=$? pid
  trap - EXIT INT TERM
  # Every worker owns a separate session, so its group contains only this run's descendants.
  for pid in "${active[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done
  if ((${#active[@]})); then
    sleep 0.1
  fi
  for pid in "${active[@]}"; do
    kill -KILL -- "-$pid" 2>/dev/null || true
    kill -KILL "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
  rm -rf -- "$results"
  exit "$code"
}

cancelled() {
  echo "structural-gates: BLOCKED - cancelled by $2." >&2
  exit "$1"
}

trap cleanup EXIT
trap 'cancelled 130 INT' INT
trap 'cancelled 143 TERM' TERM
deadline=$((SECONDS + total_timeout))

check_deadline() {
  if ((SECONDS >= deadline)); then
    echo "structural-gates: BLOCKED - total deadline exceeded (${total_timeout}s)." >&2
    exit 124
  fi
}

reap_workers() {
  local pid
  local -a remaining=()
  for pid in "${active[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      remaining+=("$pid")
    else
      wait "$pid" || true
      # A killed worker may leave its scanner alive even though its result is missing.
      kill -KILL -- "-$pid" 2>/dev/null || true
    fi
  done
  active=("${remaining[@]}")
}

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
  # Capture per gate, not in a shared filename that parallel pushes overwrite.
  CHECK_QUIET=1 timeout --foreground --kill-after=1s 600 "${gate_command[@]}" >"$results/$gate.out" 2>&1
  code=$?
  printf '%s %s\n' "$code" "$((SECONDS - started))" >"$results/$gate.status"
}
export results
export -f gate_name run_gate

for gate_path in "${gates[@]}"; do
  while ((${#active[@]} >= limit)); do
    check_deadline
    reap_workers
    if ((${#active[@]} >= limit)); then
      sleep 0.05
    fi
  done
  check_deadline
  echo "structural-gates: gate=$(gate_name "$gate_path") status=running"
  # The worker shell, not this scheduler, expands the positional parameter.
  # shellcheck disable=SC2016
  setsid bash -c 'set -uo pipefail; run_gate "$1"' -- "$gate_path" &
  active+=("$!")
done
while ((${#active[@]})); do
  check_deadline
  reap_workers
  if ((${#active[@]})); then
    sleep 0.05
  fi
done

failed=0
for gate_path in "${gates[@]}"; do
  gate="$(gate_name "$gate_path")"
  if [[ ! -f "$results/$gate.status" || ! -f "$results/$gate.out" ]] ||
     ! read -r code duration extra <"$results/$gate.status" ||
     [[ ! "$code" =~ ^[0-9]{1,3}$ || ! "$duration" =~ ^[0-9]+$ || -n "$extra" ]] ||
     ((10#$code > 255)); then
    echo "structural-gates: BLOCKED - ${gate} failed: missing or invalid result." >&2
    failed=1
    continue
  fi
  code=$((10#$code))
  if ((code == 0)); then
    echo "structural-gates: gate=${gate} status=0 duration=${duration}s"
  else
    echo "structural-gates: BLOCKED - ${gate} failed: status=${code} duration=${duration}s" >&2
    if [[ -f "$results/$gate.out" ]]; then
      sed 's/^/  /' "$results/$gate.out" >&2
    else
      echo "structural-gates: BLOCKED - ${gate} output is missing." >&2
    fi
    failed=1
  fi
done
((failed == 0)) || exit 1

echo "structural-gates: OK"
