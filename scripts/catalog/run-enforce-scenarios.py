"""Retired raw reference-sweep driver; it refuses every live run.

This driver previously built live injectors and ran `FaultInjectionHarness` in
enforce mode with an unverified approval string. Live chaos now runs only
through `GovernedChaosExecutionAdapter` (see
`scripts/catalog/run-catalog-scenario.py`). Until the ten-scenario reference
sweep is ported onto that adapter, this driver reads no environment, touches no
substrate, prints one structured refusal record, and exits with status 3, so the
protected scenario-lab sweep step fails closed.
"""

from __future__ import annotations

import json
import sys

REFUSED_EXIT = 3


def refusal() -> dict[str, object]:
    """Return the structured refusal record this retired driver emits."""

    return {
        "driver": "run-enforce-scenarios",
        "mode": "enforce",
        "outcome": "refused",
        "reason": "raw_harness_driver_retired",
        "detail": "port the reference sweep onto GovernedChaosExecutionAdapter (#94)",
        "mutation_attempted": False,
    }


def main(argv: list[str] | None = None) -> int:
    del argv
    print(json.dumps(refusal(), sort_keys=True), file=sys.stderr, flush=True)
    return REFUSED_EXIT


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
