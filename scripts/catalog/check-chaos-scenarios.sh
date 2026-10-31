#!/usr/bin/env bash
#
# check-chaos-scenarios.sh - CI gate for the chaos-scenarios catalog.
#
# Runs `load_all()` from the Core service's `fdai/core/chaos/scenario_catalog.py`, which
# fails on:
#   - schema violations (schema/chaos-scenario.schema.json),
#   - unknown expected_signal (not in core/detection/signals.py),
#   - `injector: needs-injector` scenarios landing in promoted/,
#   - duplicate scenario ids across the tree,
#   - malformed override files.
#
# Then rebuilds the compiled symptom index and checks that the on-disk
# artifact matches - a catalog PR that forgets to run
# `scripts/catalog/build-symptom-index.py` fails here instead of shipping a
# stale runtime artifact.
#
# Finally, checks that both user-facing SRE scenario inventory pages list
# every current catalog id exactly once. This keeps the published English and
# Korean inventory synchronized with catalog growth.
#
# Exit code: 0 on all-pass, non-zero on any failure. An empty catalog passes
# only when both published inventories are empty too; otherwise the freshness
# check correctly reports the stale documented ids.

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root" || exit 2
export PYTHONPATH="$repo_root/services/core-control-plane/src:$repo_root/packages/service-contracts/src${PYTHONPATH:+:$PYTHONPATH}"

if command -v uv >/dev/null 2>&1; then
    python_cmd=(uv run python)
elif command -v python3 >/dev/null 2>&1; then
    python_cmd=(python3)
else
    echo "check-chaos-scenarios: uv or python3 not found on PATH" >&2
    exit 2
fi

index_path="rule-catalog/chaos-scenarios/chaos-scenarios.index.json"
if [[ ! -f "$index_path" ]]; then
    echo "check-chaos-scenarios: missing $index_path (run scripts/catalog/build-symptom-index.py)" >&2
    exit 1
fi

summary_path="rule-catalog/chaos-scenarios/evidence/catalog-validation-summary.json"
if [[ ! -f "$summary_path" ]]; then
    echo "check-chaos-scenarios: missing $summary_path" >&2
    echo "  fix: python3 scripts/catalog/run-catalog-scenario.py --dry-run --evidence-summary $summary_path" >&2
    exit 1
fi

tmp_index="$(mktemp)"
trap 'rm -f "$tmp_index"' EXIT

PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
    "${python_cmd[@]}" - "$index_path" "$tmp_index" "$summary_path" <<'PY'
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from fdai.core.chaos.catalog_evidence import assert_catalog_summary_current
from fdai.core.chaos.scenario_catalog import ScenarioCatalogError, load_all
from fdai.core.chaos.symptom_index import build_from_entries, write_snapshot

index_path = Path(sys.argv[1])
tmp_index = Path(sys.argv[2])
summary_path = Path(sys.argv[3])

try:
    entries = load_all()
except ScenarioCatalogError as exc:
    print(f"check-chaos-scenarios: chaos-catalog validation failed: {exc}", file=sys.stderr)
    sys.exit(1)
print(f"check-chaos-scenarios: loaded {len(entries)} entries")

try:
    write_snapshot(build_from_entries(entries), tmp_index)
except Exception:
    print("check-chaos-scenarios: scripts/catalog/build-symptom-index.py failed", file=sys.stderr)
    sys.exit(1)

if index_path.read_bytes() != tmp_index.read_bytes():
    print("check-chaos-scenarios: compiled symptom index is stale", file=sys.stderr)
    print("  fix: python3 scripts/catalog/build-symptom-index.py", file=sys.stderr)
    subprocess.run(["diff", "-u", str(index_path), str(tmp_index)], check=False)
    sys.exit(1)

expected = {entry.id for entry in entries}
inventory_paths = (
    Path("docs/user-guide/sre/scenario-validation-inventory.md"),
    Path("docs/user-guide/sre/scenario-validation-inventory-ko.md"),
)
pattern = re.compile(r"`(chaos\.[a-zA-Z0-9_.-]+)`")
for path in inventory_paths:
    if not path.is_file():
        print(f"missing SRE scenario inventory: {path}", file=sys.stderr)
        print("check-chaos-scenarios: scenario inventory freshness failed", file=sys.stderr)
        sys.exit(1)
    counts = Counter(pattern.findall(path.read_text(encoding="utf-8")))
    actual = set(counts)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    duplicated = sorted(scenario_id for scenario_id, count in counts.items() if count != 1)
    if missing or extra or duplicated:
        print(f"stale SRE scenario inventory: {path}", file=sys.stderr)
        if missing:
            print(f"  missing: {missing}", file=sys.stderr)
        if extra:
            print(f"  extra: {extra}", file=sys.stderr)
        if duplicated:
            print(f"  duplicated: {duplicated}", file=sys.stderr)
        print("check-chaos-scenarios: scenario inventory freshness failed", file=sys.stderr)
        sys.exit(1)
print(f"scenario inventories list {len(expected)} catalog ids each")

try:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert_catalog_summary_current(payload, entries)
except Exception as exc:
    print(f"{exc}", file=sys.stderr)
    print("check-chaos-scenarios: tracked validation summary is stale", file=sys.stderr)
    sys.exit(1)
print(f"catalog validation summary is current: {summary_path}")
PY
rc=$?
if [[ "$rc" -ne 0 ]]; then
    exit "$rc"
fi

echo "check-chaos-scenarios: OK (catalog, symptom index, inventories match)"
