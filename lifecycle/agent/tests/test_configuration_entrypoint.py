from __future__ import annotations

import base64
import importlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fdai_deployment_cli.contracts import canonical_digest

from fdai_lifecycle_agent import cli
from fdai_lifecycle_agent.hub_client import HttpHubClient
from fdai_lifecycle_agent.inputs import (
    DirectoryArtifactStore,
    InputRejectedError,
    verify_configuration,
)
from fdai_lifecycle_agent.signatures import Ed25519ArtifactVerifier

if TYPE_CHECKING:
    from conftest import Harness

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
PRIVATE_MARKER = "https://installation-only.example.com"


def write(path: Path, value: object) -> Path:
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    path.chmod(0o600)
    return path


@pytest.fixture
def entrypoint(
    harness: Harness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[list[str], dict[str, Any]]:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    entities = {"core": "1" * 64, "operator-api": "2" * 64}
    schema = {
        "replicas": {
            "x-fdai-axis": "Release channel subscription",
            "x-fdai-owner": "customer",
        }
    }
    harness.release_document["configuration_schema"] = {
        "format": "fdai.release-configuration-schema.v1",
        "release_version": "1.5.0",
        "schema_sha256": canonical_digest(schema),
        "keys": schema,
    }
    harness.release_digest = harness.add_release(harness.release_document)
    encryption = X25519PrivateKey.generate()
    pem = serialization.Encoding.PEM
    public = serialization.PublicFormat.SubjectPublicKeyInfo
    write(private / "encryption-public.pem", encryption.public_key().public_bytes(pem, public))
    write(
        private / "encryption-private.pem",
        encryption.private_bytes(
            pem,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    write(
        private / "signing.pem",
        harness.configuration_key.private_bytes(
            pem,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    write(private / "configuration.pem", harness.public_pem(harness.configuration_key))
    write(private / "hub.pem", harness.public_pem(harness.hub_keys["hub-key-active"]))
    write(private / "release.pem", harness.public_pem(harness.release_key))
    write(
        private / "release-input.json",
        {
            "release_version": "1.5.0",
            "release_digest": harness.release_digest,
            "configuration_schema": schema,
            "sealed_keys": ["endpoint"],
            "entity_ids": list(entities.values()),
        },
    )
    write(
        private / "source.json",
        {
            "revision_id": "a" * 40,
            "environment": {},
            "sealed": {"endpoint": PRIVATE_MARKER},
            "entities": [
                {
                    "entity_id": opaque,
                    "entity_overrides": [
                        {
                            "versions": ">=1.0.0 <2.0.0",
                            "values": {"replicas": index},
                        }
                    ],
                    "sealed": {},
                }
                for index, opaque in enumerate(entities.values(), start=1)
            ],
        },
    )
    producer_main = cast(
        Callable[[list[str]], int], importlib.import_module("fdai_deployment_cli.cli").main
    )
    assert (
        producer_main(
            [
                "configuration",
                "build",
                "--release-input",
                str(private / "release-input.json"),
                "--configuration-key",
                str(private / "configuration.pem"),
                "--installation-key",
                str(private / "encryption-public.pem"),
                "--signing-key",
                str(private / "signing.pem"),
                "--input",
                str(private / "source.json"),
                "--initial-revision",
                "--destination",
                str(private / "container.json"),
                "--output",
                "json",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert PRIVATE_MARKER not in captured.out + captured.err
    container = json.loads((private / "container.json").read_bytes())
    import hashlib

    digest = hashlib.sha256(base64.b64decode(container["payload"])).hexdigest()
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    configurations = inputs / "configurations"
    configurations.mkdir(mode=0o700)
    write(configurations / f"{digest}.json", (private / "container.json").read_bytes())
    releases = inputs / "releases"
    releases.mkdir()
    release = harness.store.releases[harness.release_digest]
    write(releases / f"{harness.release_digest}.json", release.payload)
    write(releases / f"{harness.release_digest}.sig", release.signature)
    binding: dict[str, object] = {
        "format": "fdai.lifecycle-agent-configuration-binding.v1",
        "installation_id": "installation-alpha",
        "active_digest": digest,
        "entity_bindings": entities,
        "sealed_keys": ["endpoint"],
        "history": [],
    }
    write(private / "binding.json", binding)
    write(private / "state.json", harness.state_document())
    write(
        private / "policy.json",
        {
            "schema": "fdai.lifecycle-local-policy.v1",
            "entity_ids": list(entities),
            "regions": ["korea-central"],
            "capability_modes": {"action:scale-service": "enforce"},
            "destructive_allowed": False,
            "max_duration_minutes": 60,
            "entity_components": {
                key: list(value) for key, value in harness.entity_components.items()
            },
        },
    )
    harness.configuration_digest = digest
    harness.serve(harness.plan())
    arguments = [
        "poll-once",
        "--hub-url",
        "http://127.0.0.1:8740",
        "--installation-id",
        "installation-alpha",
        "--state-dir",
        str(private / "agent-state"),
        "--hub-public-key",
        str(private / "hub.pem"),
        "--hub-key-id",
        "hub-key-active",
        "--hub-key-epoch",
        "3",
        "--fencing-generation",
        "4",
        "--release-public-key",
        str(private / "release.pem"),
        "--configuration-public-key",
        str(private / "configuration.pem"),
        "--inputs-dir",
        str(inputs),
        "--current-state",
        str(private / "state.json"),
        "--local-policy",
        str(private / "policy.json"),
        "--configuration-binding",
        str(private / "binding.json"),
        "--installation-encryption-key",
        str(private / "encryption-private.pem"),
    ]
    return arguments, {"private": private, "inputs": inputs, "binding": binding}


def run(arguments: list[str], harness: Harness) -> tuple[int, list[dict[str, object]]]:
    reports: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            reports.append(json.loads(request.content))
            return httpx.Response(202)
        assert harness.hub.plan is not None
        return httpx.Response(
            200,
            json={
                "plan": {
                    "signed_payload": base64.b64encode(harness.hub.plan.signed_payload).decode(),
                    "signature": base64.b64encode(harness.hub.plan.signature).decode(),
                }
            },
        )

    def connect(url: str, seconds: float) -> HttpHubClient:
        return HttpHubClient(url, timeout_seconds=seconds, transport=httpx.MockTransport(handle))

    return cli.main(arguments, clock=lambda: NOW, connect_hub=connect), reports


def test_real_producer_container_to_native_agent_cli(
    harness: Harness,
    entrypoint: tuple[list[str], dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments, context = entrypoint
    code, reports = run(arguments, harness)
    assert code == 0
    result = capsys.readouterr()
    assert json.loads(result.out)["outcome"] == "dry-run-admitted"
    assert PRIVATE_MARKER not in result.out + result.err + json.dumps(reports)
    # A fresh CLI object with the same durable state doesn't consume or report twice.
    assert run(arguments, harness) == (0, [])
    assert json.loads(capsys.readouterr().out)["outcome"] == "already-reported"
    assert all(
        PRIVATE_MARKER.encode() not in path.read_bytes()
        for path in (context["private"] / "agent-state").iterdir()
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing-encryption",
        "missing-binding",
        "absent-encryption-file",
        "absent-binding-file",
        "identity-as-encryption",
        "public-container",
        "public-binding",
        "head",
        "scope",
        "fence",
        "revoked-hub-key",
    ],
)
def test_native_entrypoint_cannot_bypass_prerequisites(
    harness: Harness,
    entrypoint: tuple[list[str], dict[str, Any]],
    fault: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments, context = entrypoint
    private = context["private"]
    if fault.startswith("missing-"):
        flag = (
            "--installation-encryption-key"
            if fault == "missing-encryption"
            else "--configuration-binding"
        )
        index = arguments.index(flag)
        del arguments[index : index + 2]
    elif fault.startswith("absent-"):
        (
            private
            / ("encryption-private.pem" if fault == "absent-encryption-file" else "binding.json")
        ).unlink()
    elif fault == "identity-as-encryption":
        (private / "encryption-private.pem").write_bytes((private / "signing.pem").read_bytes())
    elif fault == "public-container":
        for path in (context["inputs"] / "configurations").iterdir():
            path.chmod(0o644)
    elif fault == "public-binding":
        (private / "binding.json").chmod(0o644)
    elif fault in {"head", "scope"}:
        binding = context["binding"]
        binding["active_digest" if fault == "head" else "entity_bindings"] = (
            "f" * 64 if fault == "head" else {"new-entity": "1" * 64}
        )
        write(private / "binding.json", binding)
    elif fault == "fence":
        harness.serve(harness.plan(fencing_generation=3))
    elif fault == "revoked-hub-key":
        arguments.extend(["--revoked-hub-key-id", "hub-key-active"])
    code, reports = run(arguments, harness)
    captured = capsys.readouterr()
    assert code in {0, 2}
    assert PRIVATE_MARKER not in captured.out + captured.err + json.dumps(reports)
    if code == 0:
        assert json.loads(captured.out)["outcome"] == "rejected"
    else:
        assert reports == []


@pytest.mark.parametrize(
    ("signature", "reason"),
    [
        ("missing", "configuration_signature_missing"),
        ("invalid", "configuration_signature_invalid"),
        ("valid", "configuration_malformed"),
    ],
)
def test_native_legacy_artifact_verifies_signature_before_rejecting_bad_json(
    harness: Harness, tmp_path: Path, signature: str, reason: str
) -> None:
    configurations = tmp_path / "configurations"
    configurations.mkdir()
    payload = b"{malformed legacy JSON"
    digest = harness.configuration_digest
    (configurations / f"{digest}.json").write_bytes(payload)
    if signature != "missing":
        (configurations / f"{digest}.sig").write_bytes(
            harness.configuration_key.sign(payload) if signature == "valid" else b"x" * 64
        )
    with pytest.raises(InputRejectedError) as rejected:
        verify_configuration(
            harness.plan(),
            DirectoryArtifactStore(tmp_path),
            Ed25519ArtifactVerifier(harness.configuration_key.public_key()),
        )
    assert rejected.value.reason_code == reason
    assert rejected.value.retryable is False
