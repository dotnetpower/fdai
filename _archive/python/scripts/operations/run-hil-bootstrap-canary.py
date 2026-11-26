#!/usr/bin/env python3
"""Run the deterministic local human approval bootstrap canary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "packages/service-contracts/src"))
sys.path.insert(0, str(_ROOT / "services/operator-service/src"))


def main() -> int:
    from fdai_operator_service.families.iam.hil_bootstrap_canary import (
        run_local_hil_bootstrap_canary_sync,
    )

    result = run_local_hil_bootstrap_canary_sync()
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
