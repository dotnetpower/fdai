"""Retired raw detection-latency driver; it refuses every live injection.

This driver previously called live injectors' `inject` and `stop` directly,
outside every governed safeguard. Detection latency must be measured through a
governed run instead. Until this measurement is ported onto
`GovernedChaosExecutionAdapter`, the driver reads no environment, touches no
substrate, prints one structured refusal record, and exits with status 3.
"""

from __future__ import annotations

import json
import sys

REFUSED_EXIT = 3


def refusal() -> dict[str, object]:
    """Return the structured refusal record this retired driver emits."""

    return {
        "driver": "measure-detection-latency",
        "mode": "enforce",
        "outcome": "refused",
        "reason": "raw_injection_driver_retired",
        "detail": "port detection-latency measurement onto GovernedChaosExecutionAdapter (#94)",
        "mutation_attempted": False,
    }


def main(argv: list[str] | None = None) -> int:
    del argv
    print(json.dumps(refusal(), sort_keys=True), file=sys.stderr, flush=True)
    return REFUSED_EXIT


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
