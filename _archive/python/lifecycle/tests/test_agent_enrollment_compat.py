"""The Agent's cluster-derived enrollment is exactly what the Hub accepts as a pending request."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_enrollment import sign_enrollment_payload
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from fdai_lifecycle_agent.enrollment import derive_enrollment_facts, enrollment_template
from fdai_lifecycle_agent.installation_declaration import load_declaration
from fdai_lifecycle_hub import schemas
from fdai_lifecycle_hub.enrollment import EnrollmentStatus
from fdai_lifecycle_hub.signing import verify_key_proof
from fdai_lifecycle_hub.store import HubStore

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


class Source:
    def list_entity_workloads(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        pod = {
            "spec": {"containers": [{"name": "app", "image": f"registry.example/core@{DIGEST}"}]}
        }
        deployment = {
            "metadata": {
                "name": "core",
                "namespace": "fdai-app",
                "generation": 1,
                "labels": {"fdai.io/entity": "core", "app.kubernetes.io/version": "1.4.0"},
                "annotations": {"fdai.io/schema-revision": "15"},
            },
            "spec": {"replicas": 1, "template": pod},
            "status": {
                "observedGeneration": 1,
                "replicas": 1,
                "updatedReplicas": 1,
                "availableReplicas": 1,
                "readyReplicas": 1,
            },
        }
        return [deployment], []


def test_the_hub_accepts_the_agent_derived_request_as_pending(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    declaration_path = private / "declaration.json"
    declaration_path.write_text(
        """{
  "schema": "fdai.lifecycle-installation-declaration.v1",
  "installation_id": "installation-alpha",
  "settings": {
    "channel": "stable",
    "version_range": ">=1.4.0 <2.0.0",
    "region": "korea-central",
    "allowed_regions": ["korea-central"],
    "windows": [
      {"start": "11:30:00", "duration": "PT1H", "timezone": "Asia/Seoul", "allows_downtime": false}
    ]
  },
  "configuration": {
    "schema": {"replicas": {"default": 1, "x-fdai-owner": "customer"}},
    "environment": {},
    "entity_overrides": [{"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}}]
  }
}""",
        encoding="utf-8",
    )
    declaration_path.chmod(0o600)
    key = Ed25519PrivateKey.generate()
    entities, reported = derive_enrollment_facts(Source(), namespace="fdai-app", now=NOW)
    template = enrollment_template(load_declaration(declaration_path), entities, reported)
    payload, proof = sign_enrollment_payload(template, key, NOW)

    request = schemas.enrollment_request(payload, proof)

    assert request.installation.settings.channel == "stable"
    assert request.installation.settings.product is None
    assert request.installation.reported.entities["core"].release_id == "1.4.0"
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    store = HubStore(engine)
    store.create_schema()
    try:
        store.request_enrollment(
            request,
            verify=verify_key_proof,
            now=NOW,
            requested_by="agent-object",
            requested_via="agent",
        )
        assert store.enrollment_status("installation-alpha") is EnrollmentStatus.PENDING
        (pending,) = store.list_pending_enrollments()
        assert (pending.requested_by, pending.requested_via) == ("agent-object", "agent")
        assert pending.installation.managed_entity_ids == frozenset()
    finally:
        engine.dispose()


@pytest.mark.parametrize("duration", ["PT1H", "P1D"])
def test_declared_window_durations_are_hub_parseable(duration: str) -> None:
    window = {"start": "00:00:00", "duration": duration, "timezone": "Asia/Seoul"}

    parsed = schemas.settings_json.validate_python(
        {
            "channel": "stable",
            "version_range": ">=1.0.0 <2.0.0",
            "region": "korea-central",
            "allowed_regions": ["korea-central"],
            "windows": [window],
        }
    )

    assert parsed.windows[0].timezone == "Asia/Seoul"
