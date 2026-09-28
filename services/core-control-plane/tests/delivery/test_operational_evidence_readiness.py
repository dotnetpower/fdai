"""Per-purpose Settings rows: availability never grants authority or echoes configuration."""

from __future__ import annotations

import json
from pathlib import Path

from fdai.core.operational_evidence.registry_json import content_pin
from fdai.delivery.integration_readiness import integration_projection
from fdai.delivery.operational_evidence_readiness import (
    BOUND_READBACK_PURPOSES,
    operational_evidence_projection,
)
from fdai_service_contracts.operational_evidence import OPERATIONAL_EVIDENCE_PURPOSES

from tests.core.operational_evidence.support import (
    LOCAL_PRINCIPALS,
    NOW,
    TRUST_REGISTRY,
    encode,
    grant_document,
)


def _environment(tmp_path: Path, **principals: str) -> dict[str, str]:
    grants = tmp_path / "grants.json"
    grants.write_bytes(encode(grant_document()))
    bound = {**LOCAL_PRINCIPALS, **principals}
    return {
        "FDAI_EXECUTION_VENUE": "local",
        "FDAI_OPERATIONAL_EVIDENCE_ENABLED": "1",
        "FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PATH": str(TRUST_REGISTRY),
        "FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PIN": content_pin(TRUST_REGISTRY.read_bytes()),
        "FDAI_OPERATIONAL_EVIDENCE_GRANT_REGISTRY_PATH": str(grants),
        "FDAI_OPERATIONAL_EVIDENCE_GRANT_REGISTRY_PIN": content_pin(grants.read_bytes()),
        "FDAI_OPERATIONAL_EVIDENCE_ANCHORS_JSON": json.dumps(
            {
                "schema_version": "1.0.0",
                "venue": "local",
                "anchors": [
                    {"anchor_id": key, "principal_id": value, "evidence_class": "local-loopback"}
                    for key, value in sorted(bound.items())
                ],
            }
        ),
        "FDAI_OPERATIONAL_EVIDENCE_VERIFIER_URL": "http://127.0.0.1:8791",
        "FDAI_STATE_STORE_DSN": "postgresql://placeholder-user@127.0.0.1:5433/placeholder",
    }


def _rows(
    env: dict[str, str], *, verifier_readiness: dict[str, object] | None = None
) -> dict[str, dict[str, object]]:
    rows = operational_evidence_projection(env, now=NOW, verifier_readiness=verifier_readiness)
    return {str(row["key"]): row for row in rows}


def test_default_rows_are_disabled_unavailable_and_authority_free() -> None:
    rows = _rows({})
    assert set(rows) == {
        f"operational-evidence.{purpose}" for purpose in OPERATIONAL_EVIDENCE_PURPOSES
    }
    for row in rows.values():
        assert row["available"] is False and row["enabled"] is False
        assert row["mode"] == "disabled" and row["authority_mode"] == "shadow"
        assert row["execution_authority"] is False and row["promotion_authority"] is False
        assert row["capability_state"] == "unavailable"
        assert row["reason"] == "not enabled by deployment configuration"


def test_bound_purposes_become_available_only_with_observed_writer_exclusive_readiness(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)
    unobserved = _rows(env)
    assert all(row["available"] is False for row in unobserved.values())
    assert unobserved["operational-evidence.operator-test-context-command"]["reason"] == (
        "verifier readiness with a writer-exclusive proof store is not observed"
    )
    ready = _rows(
        env,
        verifier_readiness={"state": "ready", "bound_purposes": sorted(BOUND_READBACK_PURPOSES)},
    )
    available = {key for key, row in ready.items() if row["available"]}
    assert available == {f"operational-evidence.{purpose}" for purpose in BOUND_READBACK_PURPOSES}
    for row in ready.values():
        assert row["mode"] == "shadow" and row["authority_mode"] == "shadow"
        assert row["execution_authority"] is False and row["promotion_authority"] is False
    assert "#1021" in str(ready["operational-evidence.forecast-history-changes"]["reason"])
    serialized = json.dumps(list(ready.values()))
    for value in (env["FDAI_STATE_STORE_DSN"], env["FDAI_OPERATIONAL_EVIDENCE_VERIFIER_URL"]):
        assert value not in serialized


def test_shared_verifier_identity_or_foreign_writer_reports_self_verified(tmp_path: Path) -> None:
    shared = _rows(
        _environment(tmp_path, **{"anchor:operational-evidence-verifier": "fdai_core"}),
        verifier_readiness={"state": "ready", "bound_purposes": sorted(BOUND_READBACK_PURPOSES)},
    )
    aggregate = shared.pop("operational-evidence.forecast-context")
    assert aggregate["reason"] == "the pinned registry entry or its anchors are unavailable"
    assert {row["capability_state"] for row in shared.values()} == {"self_verified"}
    foreign = _rows(
        _environment(tmp_path),
        verifier_readiness={
            "state": "self_verified",
            "bound_purposes": sorted(BOUND_READBACK_PURPOSES),
        },
    )
    row = foreign["operational-evidence.operator-test-context-command"]
    assert row["capability_state"] == "self_verified" and row["available"] is False


def test_integration_projection_lists_every_purpose_row() -> None:
    keys = {str(row["key"]) for row in integration_projection({})}
    assert {f"operational-evidence.{purpose}" for purpose in OPERATIONAL_EVIDENCE_PURPOSES} <= keys
