"""Real collector output and adversarial snapshot payloads use the same decoder."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiInventoryConfig,
    KubernetesApiInventorySource,
)
from fdai.delivery.kubernetes_connector_artifact import (
    ConnectorArtifactError,
    artifact_digest,
    decode_snapshot,
    snapshot_bytes,
)
from fdai_service_contracts.cluster_connector import ConnectorEvidence

NOW = datetime(2026, 9, 19, tzinfo=UTC)


class Auth:
    async def headers(self):
        return {}


async def collected_bytes() -> bytes:
    def respond(request: httpx.Request) -> httpx.Response:
        items = []
        if request.url.path == "/api/v1/namespaces":
            items = [
                {
                    "metadata": {
                        "name": "example",
                        "uid": "namespace-example",
                        "resourceVersion": "1",
                    }
                }
            ]
        if request.url.path == "/api/v1/pods":
            items = [
                {
                    "metadata": {
                        "namespace": "example",
                        "name": "pod-example",
                        "uid": "pod-example",
                        "resourceVersion": "2",
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "app",
                                "env": [{"name": "SECRET", "value": "must-not-transfer"}],
                                "command": ["must-not-transfer"],
                            }
                        ]
                    },
                    "status": {
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "True"}],
                        "containerStatuses": [
                            {
                                "name": "app",
                                "ready": True,
                                "restartCount": 1,
                                "lastState": {"terminated": {"exitCode": 1, "reason": "Error"}},
                            }
                        ],
                    },
                }
            ]
        return httpx.Response(200, json={"items": items, "metadata": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        snapshot = await KubernetesApiInventorySource(
            config=KubernetesApiInventoryConfig("https://example.com", "cluster-example"),
            auth=Auth(),
            http_client=client,
        ).collect()
    return snapshot_bytes(snapshot)


def envelope(content: bytes) -> ConnectorEvidence:
    body = json.loads(content)
    return ConnectorEvidence.model_validate(
        {
            "scope": {
                "deployment_ref": "example",
                "cluster_ref": "cluster-example",
                "connector_id": "example",
                "enrollment_revision": 1,
            },
            "capability": "inventory.snapshot",
            "stream_id": "example",
            "sequence": 1,
            "observed_at": body["observed_at"],
            "producer_revision": "sha256:" + "a" * 64,
            "artifact_digest": artifact_digest(content),
            "artifact_bytes": len(content),
            "namespaces": ["example"],
            "complete": True,
        }
    )


async def test_real_collector_roundtrip_discards_raw_secrets() -> None:
    content = await collected_bytes()
    assert b"must-not-transfer" not in content
    restored = decode_snapshot(content, envelope(content), allow_cluster_resources=False)
    assert len(restored.resources) == 2
    assert snapshot_bytes(restored) == content


@pytest.mark.parametrize(
    "field,value",
    [
        ("cluster_ref", "foreign"),
        ("namespace", "foreign"),
        ("uid", "foreign"),
        ("kind", "Secret"),
        ("environment", {"SECRET": "hidden"}),
        ("restart_count", True),
    ],
)
async def test_malformed_resource_rejected(field: str, value: object) -> None:
    body = json.loads(await collected_bytes())
    body["resources"][-1]["props"][field] = value
    content = json.dumps(body).encode()
    with pytest.raises(ConnectorArtifactError):
        decode_snapshot(content, envelope(content), allow_cluster_resources=False)


async def test_digest_size_and_namespace_coverage_are_required() -> None:
    content = await collected_bytes()
    packet = envelope(content)
    with pytest.raises(ConnectorArtifactError):
        decode_snapshot(content + b" ", packet, allow_cluster_resources=False)
    with pytest.raises(ConnectorArtifactError):
        decode_snapshot(
            content,
            packet.model_copy(update={"namespaces": ("example", "other")}),
            allow_cluster_resources=False,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("probe_kinds", [{"container_name": 1, "probe_kind": "liveness"}]),
        ("probe_kinds", [{"container_name": "app", "probe_kind": "arbitrary"}]),
        ("diagnostic_conditions", [{"type": "Ready", "status": "healthy"}]),
        ("diagnostic_conditions", [{"type": "Ready", "status": "True", "message": "private"}]),
        (
            "container_terminations",
            [{"container_name": "app", "observation_kind": "current", "exit_code": True}],
        ),
        ("container_resources", [{"container_name": "app"}]),
    ],
)
async def test_nested_diagnostic_records_are_strict(field: str, value: object) -> None:
    body = json.loads(await collected_bytes())
    body["resources"][-1]["props"][field] = value
    content = json.dumps(body).encode()
    with pytest.raises(ConnectorArtifactError):
        decode_snapshot(content, envelope(content), allow_cluster_resources=False)
