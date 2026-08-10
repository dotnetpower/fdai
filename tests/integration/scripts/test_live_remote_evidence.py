from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fdai_service_contracts.compatibility import validate_peer_upgrade_receipt
from scripts.quality.architecture.live_remote_evidence import (
    OBSERVATION_KINDS,
    SERVICE_IDS,
    build_live_remote_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPATIBILITY_PATH = (
    REPO_ROOT / "packages/service-contracts/src/fdai_service_contracts/compatibility-manifest.json"
)


def _digest(seed: int) -> str:
    return f"sha256:{seed:064x}"


def _remote() -> dict[str, Any]:
    services = []
    for service_index, service_id in enumerate(SERVICE_IDS):
        stages = []
        for stage_index, name in enumerate(("rollback", "restore")):
            seed = 1000 + service_index * 100 + stage_index * 10
            stages.append(
                {
                    "name": name,
                    "plan": {
                        "workflow_run_id": seed,
                        "plan_digest": _digest(seed + 1),
                        "context_digest": _digest(seed + 2),
                    },
                    "apply": {
                        "workflow_run_id": seed + 5,
                        "peer_receipt_artifact_sha256": _digest(seed + 3),
                        "started_at": f"2026-08-10T00:{service_index}{stage_index}:00Z",
                        "completed_at": f"2026-08-10T00:{service_index}{stage_index}:30Z",
                        "observations": {
                            kind: {
                                "kind": kind,
                                "service_id": service_id,
                                "observed": True,
                                "verification": f"{name}-{kind}",
                                "workflow_run_id": seed + 5,
                            }
                            for kind in OBSERVATION_KINDS
                        },
                    },
                }
            )
        services.append({"id": service_id, "stages": stages})
    return {
        "repository": "dotnetpower/fdai",
        "workflow": ".github/workflows/service-deploy.yml",
        "controls_commit_sha": "a" * 40,
        "services": services,
    }


def _compatibility() -> dict[str, Any]:
    value = json.loads(COMPATIBILITY_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_live_records_are_deterministic_remote_projections() -> None:
    compatibility = _compatibility()
    remote = _remote()

    first = build_live_remote_evidence(compatibility, remote)
    second = build_live_remote_evidence(compatibility, remote)

    assert first == second
    receipts, manifest = first
    assert len(receipts) == 10
    assert len(manifest["artifacts"]) == 70
    for receipt in receipts:
        assert tuple(receipt["observation_refs"]) == OBSERVATION_KINDS
        validate_peer_upgrade_receipt(
            compatibility,
            receipt,
            required_proof_kind="live",
            evidence_manifest=manifest,
        )


def test_live_records_bind_actual_serial_peer_versions() -> None:
    receipts, _manifest = build_live_remote_evidence(_compatibility(), _remote())
    by_key = {(item["service_id"], item["direction"]): item for item in receipts}

    ingestion_rollback = by_key[("document-ingestion-api", "rollback")]
    assert ingestion_rollback["peer_versions_before"]["operator-service"] == "1.0.0"
    assert ingestion_rollback["peer_versions_before"]["core-control-plane"] == "1.1.0"
    executor_migration = by_key[("isolated-executor", "migration")]
    assert executor_migration["peer_versions_before"]["core-control-plane"] == "1.1.0"
    assert executor_migration["peer_versions_before"]["document-processing-worker"] == "1.1.0"


def test_live_records_change_when_remote_receipt_changes() -> None:
    remote = _remote()
    original = build_live_remote_evidence(_compatibility(), remote)
    remote["services"][0]["stages"][0]["apply"]["observations"]["health"]["verification"] = (
        "changed-health-proof"
    )

    changed = build_live_remote_evidence(_compatibility(), remote)

    assert changed != original


def test_live_records_reject_unobserved_remote_content() -> None:
    remote = _remote()
    remote["services"][0]["stages"][0]["apply"]["observations"]["health"]["observed"] = False

    with pytest.raises(ValueError, match="health observation is invalid"):
        build_live_remote_evidence(_compatibility(), remote)
