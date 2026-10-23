from __future__ import annotations

import json
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_lifecycle_agent.cli import load_local_policy
from fdai_lifecycle_agent.runtime_bundle import RuntimeBundle
from fdai_lifecycle_hub import schemas
from fdai_lifecycle_hub.execution_settings import ApplicationBindingRequest
from fdai_lifecycle_hub.operations import ReleasePublicationRequest
from fdai_lifecycle_hub.signing import verify_key_proof

from fdai_lifecycle_manager.preparation import prepare_installation


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed Git executable in a private test checkout.
        ["git", *arguments],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _checkout(root: Path) -> None:
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "user@example.com")
    _git(root, "config", "user.name", "Example")
    (root / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-m", "source")


def _container() -> dict[str, object]:
    return {
        "name": "operator-service",
        "image_component": "operator-service",
        "resources": {
            "requests": {"cpu": "250m", "memory": "512Mi"},
            "limits": {"cpu": "1000m", "memory": "1024Mi"},
        },
        "securityContext": {
            "runAsNonRoot": True,
            "readOnlyRootFilesystem": True,
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
        },
        "ports": [{"name": "http", "containerPort": 8000}],
        "readinessProbe": {"httpGet": {"path": "/healthz", "port": "http"}},
        "envFrom": [{"configMapRef": {"name": "operator-service", "optional": False}}],
        "env": [
            {
                "name": "FDAI_DATABASE_URL",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": "operator-service-database",
                        "key": "FDAI_DATABASE_URL",
                    }
                },
            }
        ],
        "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],  # noqa: S108
    }


def _runtime_bundle() -> dict[str, object]:
    labels = {"azure.workload.identity/use": "true"}
    pod = {
        "metadata": {"labels": labels},
        "spec": {
            "containers": [_container()],
            "serviceAccountName": "operator-service",
            "automountServiceAccountToken": False,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 65532,
                "runAsGroup": 65532,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "128Mi"}}],
        },
    }
    return {
        "format": "fdai.application-runtime-bundle.v1",
        "product": "fdai",
        "namespace": "fdai-system",
        "objects": [
            {
                "entity_id": "operator-canary",
                "kind": "Deployment",
                "name": "operator-hub-canary",
                "spec": {"replicas": 1, "template": pod},
            },
            {
                "entity_id": "operator-canary",
                "kind": "Service",
                "name": "operator-hub-canary",
                "spec": {"ports": [{"port": 80, "targetPort": "http"}]},
            },
        ],
    }


def _public_key(path: Path) -> None:
    path.write_bytes(
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    path.chmod(0o600)


def test_prepare_builds_closed_signed_installation_inputs(tmp_path: Path) -> None:
    checkout = tmp_path / "source"
    _checkout(checkout)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    bundle = private / "runtime-bundle.json"
    bundle.write_text(json.dumps(_runtime_bundle()), encoding="utf-8")
    bundle.chmod(0o600)
    images = private / "images.json"
    images.write_text(
        json.dumps(
            {"operator-service": ("registry.example.com/fdai-operator-service@sha256:" + "a" * 64)}
        ),
        encoding="utf-8",
    )
    images.chmod(0o600)
    hub_key = private / "hub.pem"
    release_key = private / "release.pem"
    _public_key(hub_key)
    _public_key(release_key)
    destination = tmp_path / "prepared"
    now = datetime(2026, 10, 24, 2, tzinfo=UTC)

    receipt = prepare_installation(
        source_root=checkout,
        destination=destination,
        runtime_bundle_path=bundle,
        component_images_path=images,
        hub_public_key_path=hub_key,
        release_public_key_path=release_key,
        installation_id="installation-alpha",
        entity_id="operator-canary",
        product="fdai",
        release_id="1.0.0",
        channel="DEV",
        region="westus3",
        actor="example-operator",
        now=now,
    )

    assert receipt.source_commit == _git(checkout, "rev-parse", "HEAD")
    assert receipt.deployment_ready is False
    assert (
        RuntimeBundle.model_validate_json((destination / "runtime-bundle.json").read_bytes()).digest
        == receipt.runtime_bundle_digest
    )
    assert load_local_policy(destination / "local-policy.json")["product"] == "fdai"
    publication = ReleasePublicationRequest.model_validate_json(
        (destination / "release-publication-request.json").read_bytes()
    )
    assert publication.manifest_digest == receipt.release_digest
    binding = ApplicationBindingRequest.model_validate_json(
        (destination / "application-binding.json").read_bytes()
    )
    assert binding.expected_settings_digest == receipt.settings_digest
    signed = schemas.SignedEnrollment.model_validate_json(
        (destination / "signed-enrollment.json").read_bytes()
    )
    enrollment = schemas.enrollment_request(signed.signed_payload, signed.proof)
    assert verify_key_proof(
        public_key=enrollment.installation_key,
        payload=enrollment.signed_payload,
        signature=enrollment.proof,
    )
    assert enrollment.installation.installation_id == "installation-alpha"
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in destination.rglob("*")
        if path.is_file()
    )


def test_prepare_rejects_component_set_drift_and_removes_partial_output(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "source"
    _checkout(checkout)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    bundle = private / "runtime-bundle.json"
    bundle.write_text(json.dumps(_runtime_bundle()), encoding="utf-8")
    bundle.chmod(0o600)
    images = private / "images.json"
    images.write_text("{}", encoding="utf-8")
    images.chmod(0o600)
    hub_key = private / "hub.pem"
    release_key = private / "release.pem"
    _public_key(hub_key)
    _public_key(release_key)
    destination = tmp_path / "prepared"

    with pytest.raises(ValueError, match="differs"):
        prepare_installation(
            source_root=checkout,
            destination=destination,
            runtime_bundle_path=bundle,
            component_images_path=images,
            hub_public_key_path=hub_key,
            release_public_key_path=release_key,
            installation_id="installation-alpha",
            entity_id="operator-canary",
            product="fdai",
            release_id="1.0.0",
            channel="DEV",
            region="westus3",
            actor="example-operator",
            now=datetime(2026, 10, 24, 2, tzinfo=UTC),
        )

    assert not destination.exists()
