#!/usr/bin/env python3
"""Run the deterministic independent-service remote evidence gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.quality.architecture.remote_service_evidence import (
    RemoteEvidenceError,
    validate_remote_service_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = REPO_ROOT / "config" / "independent-services.json"
DEFAULT_EVIDENCE = REPO_ROOT / "config" / "independent-service-remote-evidence.json"


def _load_object(path: Path, label: str) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RemoteEvidenceError(f"{label} must contain a JSON object")
    return value


def main() -> int:
    """Validate one tracked, customer-agnostic remote evidence aggregate."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    try:
        summary = validate_remote_service_evidence(
            _load_object(args.manifest, "independent-services manifest"),
            _load_object(args.evidence, "remote service evidence"),
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"check-remote-service-evidence: ERROR: {exc}")
        return 1
    print(
        "check-remote-service-evidence: OK "
        f"(plan_apply={summary.service_plan_apply_receipts} "
        f"transitions={summary.service_upgrade_and_rollback_proofs} "
        f"plans={summary.protected_plan_runs} applies={summary.protected_apply_runs} "
        f"peer_receipts={summary.peer_isolation_receipts})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
