#!/usr/bin/env bash
#
# check-stewardship.sh - validate config/agent-stewardship.yaml.
#
# Three guards (see docs/roadmap/interfaces/agent-stewardship-and-handover.md
# § 7.4):
#
#   1. Role-field guard: the stewardship file is an accountability + notification
#      OVERLAY. It MUST NOT declare any fork-locked ActionType role field
#      (executor / judge / approver / initiators / auditor); those live only in
#      the ontology (agent-pantheon.instructions.md). A stray top-level key of
#      that name means someone tried to repoint execution authority here.
#   2. Agent-name integrity: the `agents:` block MUST name exactly the 15
#      pantheon members (parity with PANTHEON_NAMES is additionally pinned by
#      tests/core/stewardship/test_pantheon_parity.py).
#   3. Maintainer floor: at least 1 maintainer must be declared.
#
# Placeholder policy (all-zero upstream, real ids in a fork) is enforced by the
# shared check-guids.sh gate and by the resolver at startup, so it is not
# repeated here.
#
# Exit codes: 0 clean / skip, 1 on any violation.

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

FILE="config/agent-stewardship.yaml"

if [[ ! -f "$FILE" ]]; then
    echo "check-stewardship: $FILE not present - skipping."
    exit 0
fi

# --- Guard 1: no ActionType role field may be declared -----------------------
if grep -nE '^[[:space:]]*(executor|judge|approver|initiators|auditor):' "$FILE"; then
    echo "check-stewardship: forbidden ActionType role field in $FILE" >&2
    echo "  stewardship is an overlay; role bindings live in the fork-locked ontology." >&2
    exit 1
fi

# --- Guards 2 + 3: structural validation via a tiny Python shim ---------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "check-stewardship: python3 not found - skipping structural check." >&2
    exit 0
fi

python3 - "$FILE" <<'PY'
import sys

try:
    import yaml
except ModuleNotFoundError:
    print("check-stewardship: PyYAML unavailable - skipping structural check.")
    sys.exit(0)

# The 15 pantheon names. Parity with PANTHEON_NAMES is enforced by
# tests/core/stewardship/test_pantheon_parity.py; this list is the CI-side
# mirror so the gate has no import dependency on src/fdai.
EXPECTED = {
    "Odin", "Thor", "Forseti", "Huginn", "Heimdall", "Vidar", "Var", "Bragi",
    "Saga", "Mimir", "Muninn", "Norns", "Njord", "Freyr", "Loki",
}

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    raw = yaml.safe_load(fh)

if not isinstance(raw, dict) or not isinstance(raw.get("stewardship"), dict):
    print(f"check-stewardship: {path}: missing top-level 'stewardship' mapping", file=sys.stderr)
    sys.exit(1)

st = raw["stewardship"]
agents = st.get("agents") or {}
keys = set(agents)

missing = EXPECTED - keys
extra = keys - EXPECTED
if missing:
    print(f"check-stewardship: agents missing: {', '.join(sorted(missing))}", file=sys.stderr)
if extra:
    print(f"check-stewardship: agents not in pantheon: {', '.join(sorted(extra))}", file=sys.stderr)
if missing or extra:
    sys.exit(1)

maintainers = st.get("maintainers") or []
if not isinstance(maintainers, list) or len(maintainers) < 1:
    print("check-stewardship: at least 1 maintainer is required", file=sys.stderr)
    sys.exit(1)

print(f"check-stewardship: OK ({len(keys)} agents, {len(maintainers)} maintainer(s))")
PY
