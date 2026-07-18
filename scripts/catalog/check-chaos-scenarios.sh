#!/usr/bin/env bash
#
# check-chaos-scenarios.sh - CI gate for the chaos-scenarios catalog.
#
# Runs `load_all()` from `src/fdai/core/chaos/scenario_catalog.py`, which
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

if command -v uv >/dev/null 2>&1; then
    python_cmd=(uv run python)
elif command -v python3 >/dev/null 2>&1; then
    python_cmd=(python3)
else
    echo "check-chaos-scenarios: uv or python3 not found on PATH" >&2
    exit 2
fi

# ---- 1. load_all() must succeed ------------------------------------------

if ! output="$(PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" "${python_cmd[@]}" -c '
import sys
from fdai.core.chaos.scenario_catalog import ScenarioCatalogError, load_all
try:
    entries = load_all()
except ScenarioCatalogError as exc:
    print(f"chaos-catalog validation failed: {exc}", file=sys.stderr)
    sys.exit(1)
print(f"loaded {len(entries)} entries")
' 2>&1)"; then
    printf 'check-chaos-scenarios: %s\n' "$output" >&2
    exit 1
fi
printf 'check-chaos-scenarios: %s\n' "$output"

# ---- 2. compiled symptom-index artifact matches load_all() ---------------

index_path="rule-catalog/chaos-scenarios/chaos-scenarios.index.json"

if [[ ! -f "$index_path" ]]; then
    echo "check-chaos-scenarios: missing $index_path (run scripts/catalog/build-symptom-index.py)" >&2
    exit 1
fi

# Regenerate to a temp file and diff. This catches "author added / removed
# a scenario but forgot to rebuild the index".
tmp_index="$(mktemp)"
trap 'rm -f "$tmp_index"' EXIT

if ! PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
    "${python_cmd[@]}" scripts/catalog/build-symptom-index.py --out "$tmp_index" >/dev/null 2>&1; then
    echo "check-chaos-scenarios: scripts/catalog/build-symptom-index.py failed" >&2
    exit 1
fi

if ! diff -q "$index_path" "$tmp_index" >/dev/null; then
    echo "check-chaos-scenarios: compiled symptom index is stale" >&2
    echo "  fix: python3 scripts/catalog/build-symptom-index.py" >&2
    diff -u "$index_path" "$tmp_index" | head -40 >&2 || true
    exit 1
fi

# ---- 3. user-facing scenario inventories match load_all() ----------------

if ! PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
    "${python_cmd[@]}" - <<'PY'
import re
import sys
from collections import Counter
from pathlib import Path

from fdai.core.chaos.scenario_catalog import load_all

expected = {entry.id for entry in load_all()}
inventory_paths = (
    Path("docs/user-guide/sre/scenario-validation-inventory.md"),
    Path("docs/user-guide/sre/scenario-validation-inventory-ko.md"),
)
pattern = re.compile(r"`(chaos\.[a-zA-Z0-9_.-]+)`")

for path in inventory_paths:
    if not path.is_file():
        print(f"missing SRE scenario inventory: {path}", file=sys.stderr)
        raise SystemExit(1)
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
        raise SystemExit(1)

print(f"scenario inventories list {len(expected)} catalog ids each")
PY
then
    echo "check-chaos-scenarios: scenario inventory freshness failed" >&2
    exit 1
fi

# ---- 4. tracked validation summary matches the current catalog -----------

summary_path="rule-catalog/chaos-scenarios/evidence/catalog-validation-summary.json"
if [[ ! -f "$summary_path" ]]; then
    echo "check-chaos-scenarios: missing $summary_path" >&2
    echo "  fix: python3 scripts/catalog/run-catalog-scenario.py --dry-run --evidence-summary $summary_path" >&2
    exit 1
fi

if ! PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
    "${python_cmd[@]}" - "$summary_path" <<'PY'
import json
import sys
from pathlib import Path

from fdai.core.chaos.catalog_evidence import assert_catalog_summary_current
from fdai.core.chaos.scenario_catalog import load_all

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
assert_catalog_summary_current(payload, load_all())
print(f"catalog validation summary is current: {path}")
PY
then
    echo "check-chaos-scenarios: tracked validation summary is stale" >&2
    exit 1
fi

echo "check-chaos-scenarios: OK (catalog, symptom index, inventories match)"
