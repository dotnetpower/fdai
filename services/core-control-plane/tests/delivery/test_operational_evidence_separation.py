"""The verifier workload refuses to start when a binding could hide a shared identity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.core.operational_evidence.registry_json import content_pin
from fdai.core.operational_evidence.separation import VerifierSeparationError
from fdai.delivery.operational_evidence_server import build_verifier_workload

from tests.core.operational_evidence.support import NOW, anchors_json, encode, trust_bytes
from tests.delivery.test_operational_evidence_venue import _workload_env

_REBOUND = {
    "FDAI_OPERATIONAL_EVIDENCE_ANCHORS_JSON": anchors_json(
        overrides={"anchor:operational-evidence-verifier": "fdai_core"}
    )
}


def _registry_env(tmp_path: Path, *, core_runtime_binding: bool) -> dict[str, str]:
    document = json.loads(trust_bytes())
    if core_runtime_binding:
        for entry in document["purposes"]:
            entry["verifiers"].append(
                {
                    **entry["verifiers"][0],
                    "verifier_version": "1.1.0",
                    "trust_anchor_id": "anchor:core-runtime",
                    "valid_from": NOW.isoformat(),
                }
            )
    path = tmp_path / "trust-registry.json"
    path.write_bytes(encode(document))
    return {
        "FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PATH": str(path),
        "FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PIN": content_pin(path.read_bytes()),
        **_REBOUND,
    }


def test_verifier_sharing_core_identity_refuses_to_start(tmp_path: Path) -> None:
    with pytest.raises(VerifierSeparationError):
        build_verifier_workload(
            _workload_env(tmp_path, **_registry_env(tmp_path, core_runtime_binding=False)),
            root=tmp_path,
        )
    with pytest.raises(RuntimeError, match="principal or store is unbound"):
        build_verifier_workload(
            _workload_env(tmp_path, **_registry_env(tmp_path, core_runtime_binding=True)),
            root=tmp_path,
        )
