"""Exercise the installed CLI grammar in fresh, network-denied subprocesses."""

from __future__ import annotations

import base64
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_configuration_package import (
    SignedConfigurationPackage,
    decrypt_configuration_identifiers,
)

SOURCE = Path(__file__).resolve().parents[1] / "src"
ENTRY = """
import sys
def guard(event, args):
    if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "builtins.input"}:
        raise RuntimeError("external operation forbidden")
sys.addaudithook(guard)
from fdai_deployment_cli.cli import main
raise SystemExit(main())
"""


def _write(path: Path, value: object) -> Path:
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    path.chmod(0o600)
    return path


@dataclass
class Case:
    root: Path
    signing: Ed25519PrivateKey
    recipient: X25519PrivateKey
    release: dict[str, object]
    source: dict[str, object]

    def run(self, operation: str, *extra: str | Path) -> subprocess.CompletedProcess[str]:
        arguments = [
            operation,
            "--release-input",
            str(self.root / "release.json"),
            "--configuration-key",
            str(self.root / "configuration.pem"),
            "--installation-key",
            str(self.root / "installation.pem"),
            "--output",
            "json",
        ]
        if operation == "build":
            arguments += [
                "--input",
                str(self.root / "source.json"),
                "--signing-key",
                str(self.root / "signing.pem"),
            ]
        return self.invoke("configuration", *arguments, *(str(item) for item in extra))

    def invoke(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", ENTRY, *arguments],
            env={
                **os.environ,
                "PYTHONPATH": str(SOURCE),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PATH": str(self.root / "no-tools"),
            },
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def build(self, name: str, *history: Path) -> Path:
        destination = self.root / name
        result = self.run("build", "--destination", destination, *self.chain(history))
        assert result.returncode == 0, result.stderr
        return destination

    def chain(self, history: tuple[Path, ...]) -> list[str]:
        if not history:
            return ["--initial-revision"]
        head = json.loads(history[-1].read_bytes())
        import hashlib

        digest = hashlib.sha256(base64.b64decode(head["payload"])).hexdigest()
        return [
            "--expected-predecessor",
            digest,
            *(item for path in history for item in ("--history", str(path))),
        ]


@pytest.fixture
def case(tmp_path: Path) -> Case:
    tmp_path.chmod(0o700)
    signing = Ed25519PrivateKey.generate()
    recipient = X25519PrivateKey.generate()
    _write(
        tmp_path / "signing.pem",
        signing.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    for name, key in (
        ("configuration", signing.public_key()),
        ("installation", recipient.public_key()),
    ):
        _write(
            tmp_path / f"{name}.pem",
            key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ),
        )
    schema = {
        "replicas": {
            "default": 1,
            "x-fdai-axis": "deployment-environment",
            "x-fdai-owner": "customer",
        },
        "credential_ref": {"x-fdai-axis": "deployment-environment", "x-fdai-owner": "customer"},
    }
    release: dict[str, object] = {
        "release_version": "1.5.0",
        "configuration_schema": schema,
        "sealed_keys": ["endpoint"],
    }
    source: dict[str, object] = {
        "revision_id": "a" * 40,
        "environment": {"credential_ref": "example-secret"},
        "entity_overrides": [{"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}}],
        "sealed": {"endpoint": "https://example.com/private-identifier"},
    }
    _write(tmp_path / "release.json", release)
    _write(tmp_path / "source.json", source)
    return Case(tmp_path, signing, recipient, release, source)


def _refused(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 3
    assert not result.stdout
    assert "configuration operation refused" in result.stderr
    assert "Traceback" not in result.stderr
    assert "private-identifier" not in result.stderr
    assert "PRIVATE KEY" not in result.stderr


def _multi_entity(case: Case) -> None:
    entity_ids = ["1" * 64, "2" * 64]
    case.release["entity_ids"] = entity_ids
    case.release["release_digest"] = "f" * 64
    overrides = case.source.pop("entity_overrides")
    case.source["entities"] = [
        {
            "entity_id": entity_id,
            "entity_overrides": overrides,
            "sealed": {"endpoint": f"https://example.com/{index}-private-identifier"},
        }
        for index, entity_id in enumerate(entity_ids)
    ]
    _write(case.root / "release.json", case.release)
    _write(case.root / "source.json", case.source)


def test_actual_multi_entity_cli_producer_consumer_and_retry(case: Case) -> None:
    _multi_entity(case)
    first = case.build("multi.json")
    artifact = json.loads(first.read_bytes())
    document = json.loads(base64.b64decode(artifact["payload"]))
    assert document["format"] == "fdai.lifecycle-configuration-package.v2"
    assert [entry["entity_id"] for entry in document["configuration"]["entities"]] == [
        "1" * 64,
        "2" * 64,
    ]
    assert b"private-identifier" not in base64.b64decode(artifact["payload"])
    verified = case.run("verify", "--package", first, "--initial-revision")
    assert verified.returncode == 0, verified.stderr
    result = json.loads(verified.stdout)
    assert result["production_release_eligibility"] == "unverified"
    assert not result["trust_registered"] and not result["deployment_activated"]
    retried = case.build("retry.json", first)
    assert retried.read_bytes() == first.read_bytes()


@pytest.mark.parametrize(
    "problem",
    ["missing", "duplicate", "coverage", "unknown-key", "secret", "plaintext-id", "mixed-legacy"],
)
def test_multi_entity_cli_blocks_incomplete_or_mixed_inputs(case: Case, problem: str) -> None:
    _multi_entity(case)
    entities = case.source["entities"]
    assert isinstance(entities, list)
    if problem == "missing":
        entities.pop()
    elif problem == "duplicate":
        entities.append(entities[0])
    elif problem == "plaintext-id":
        entities[0]["entity_id"] = "example-customer-resource"
    elif problem == "mixed-legacy":
        case.source["entity_overrides"] = []
    elif problem == "coverage":
        entities[1]["entity_overrides"] = [{"versions": ">=2.0.0 <3.0.0", "values": {}}]
    else:
        key = "password" if problem == "secret" else "unknown"
        entities[1]["entity_overrides"] = [
            {"versions": ">=1.0.0 <2.0.0", "values": {key: "private-identifier"}}
        ]
    _write(case.root / "source.json", case.source)
    destination = case.root / "refused.json"
    _refused(case.run("build", "--destination", destination, "--initial-revision"))
    assert not destination.exists()


@pytest.mark.parametrize("field", ["entity_ids", "release_version", "release_digest"])
def test_multi_entity_cli_requires_independent_selection_and_release(
    case: Case, field: str
) -> None:
    _multi_entity(case)
    package = case.build("multi.json")
    case.release[field] = (
        ["1" * 64]
        if field == "entity_ids"
        else ("1.5.1" if field == "release_version" else "e" * 64)
    )
    _write(case.root / "release.json", case.release)
    _refused(case.run("verify", "--package", package, "--initial-revision"))


def test_actual_cli_build_verify_seal_privacy_and_retry(case: Case) -> None:
    first = case.build("first.json")
    artifact = json.loads(first.read_bytes())
    payload = base64.b64decode(artifact["payload"])
    package = SignedConfigurationPackage(payload, base64.b64decode(artifact["signature"]))
    assert b"private-identifier" not in payload
    assert b"PRIVATE KEY" not in first.read_bytes()
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    schema = case.release["configuration_schema"]
    assert isinstance(schema, dict)
    assert (
        decrypt_configuration_identifiers(
            package,
            configuration_key=case.signing.public_key(),
            installation_key=case.recipient,
            configuration_schema=schema,
            sealed_keys=frozenset({"endpoint"}),
        )
        == case.source["sealed"]
    )
    result = case.run("verify", "--package", first, "--initial-revision")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["verified"] is True
    assert report["package_digest"] == package.digest
    assert report["production_release_eligibility"] == "unverified"
    assert report["trust_registered"] is False
    assert report["deployment_activated"] is False
    assert "private-identifier" not in result.stdout + result.stderr
    assert "example-secret" not in result.stdout + result.stderr
    for key_line in (case.root / "signing.pem").read_text().splitlines():
        assert key_line not in result.stdout + result.stderr
    retry = case.build("retry.json", first)
    assert retry.read_bytes() == first.read_bytes()
    no_clobber = case.run("build", "--destination", first, "--initial-revision")
    _refused(no_clobber)
    assert retry.read_bytes() == first.read_bytes()


def test_actual_cli_payload_limit_matches_builder_and_reader(case: Case) -> None:
    payload_limit = 1024 * 1024
    schema = case.release["configuration_schema"]
    environment = case.source["environment"]
    assert isinstance(schema, dict) and isinstance(environment, dict)
    schema["notes"] = {"x-fdai-axis": "deployment-environment", "x-fdai-owner": "customer"}
    environment["notes"] = ""
    _write(case.root / "release.json", case.release)
    _write(case.root / "source.json", case.source)
    small = json.loads(case.build("small.json").read_bytes())
    environment["notes"] = "x" * (payload_limit - len(base64.b64decode(small["payload"])))
    source_file = _write(case.root / "source.json", case.source)
    assert source_file.stat().st_size < payload_limit
    accepted = case.build("exact-limit.json")
    original = accepted.read_bytes()
    artifact = json.loads(original)
    payload = base64.b64decode(artifact["payload"])
    assert len(payload) == payload_limit
    verified = case.run("verify", "--package", accepted, "--initial-revision")
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["verified"] is True

    environment["notes"] += "x"
    _write(source_file, case.source)
    assert source_file.stat().st_size < payload_limit
    assert (case.root / "release.json").stat().st_size < payload_limit
    destination = case.root / "overflow.json"
    _refused(case.run("build", "--destination", destination, "--initial-revision"))
    assert not destination.exists()
    _refused(case.run("build", "--destination", accepted, "--initial-revision"))
    assert accepted.read_bytes() == original

    # A valid signature cannot admit the same manifest expanded by one byte.
    document = json.loads(payload)
    document["configuration"]["environment"]["notes"] += "x"
    oversized = canonical_bytes(document)
    assert len(oversized) == payload_limit + 1
    artifact["payload"] = base64.b64encode(oversized).decode()
    artifact["signature"] = base64.b64encode(case.signing.sign(oversized)).decode()
    oversized_file = _write(case.root / "oversized-signed.json", artifact)
    _refused(case.run("verify", "--package", oversized_file, "--initial-revision"))
    assert accepted.read_bytes() == original


def test_actual_cli_chain_gap_fork_reorder_and_old_revision(case: Case) -> None:
    first = case.build("first.json")
    case.source["revision_id"] = "b" * 40
    _write(case.root / "source.json", case.source)
    second = case.build("second.json", first)
    fork = case.build("fork.json")
    success = case.run("verify", "--package", second, *case.chain((first,)))
    assert success.returncode == 0, success.stderr
    for candidate, history in (
        (second, ()),
        (fork, (first,)),
        (first, (first, second)),
        (second, (second, first)),
    ):
        _refused(case.run("verify", "--package", candidate, *case.chain(history)))
    case.source["revision_id"] = "a" * 40
    _write(case.root / "source.json", case.source)
    _refused(
        case.run("build", "--destination", case.root / "old.json", *case.chain((first, second)))
    )
    assert not (case.root / "old.json").exists()
    _refused(
        case.run(
            "verify", "--package", second, "--history", first, "--expected-predecessor", "0" * 64
        )
    )
    _refused(case.run("verify", "--package", second, "--history", first, "--initial-revision"))


@pytest.mark.parametrize(
    "change", ["signature", "payload", "unsigned", "format", "base64", "extra"]
)
def test_actual_cli_rejects_artifact_tampering(case: Case, change: str) -> None:
    package = case.build("package.json")
    artifact = json.loads(package.read_bytes())
    if change == "signature":
        artifact["signature"] = base64.b64encode(b"x" * 64).decode()
    elif change == "payload":
        payload = json.loads(base64.b64decode(artifact["payload"]))
        payload["revision_id"] = "b" * 40
        artifact["payload"] = base64.b64encode(json.dumps(payload).encode()).decode()
    elif change == "unsigned":
        artifact["signature"] = ""
    elif change == "format":
        artifact["format"] = "unrecognized"
    elif change == "base64":
        artifact["payload"] = "!bad"
    else:
        artifact["extra"] = "private-identifier"
    _write(package, artifact)
    _refused(case.run("verify", "--package", package, "--initial-revision"))


@pytest.mark.parametrize("change", ["schema", "version", "classification", "signer", "recipient"])
def test_actual_cli_requires_independent_release_and_keys(case: Case, change: str) -> None:
    package = case.build("package.json")
    if change == "schema":
        case.release["configuration_schema"] = {}
    elif change == "version":
        case.release["release_version"] = "1.6.0"
    elif change == "classification":
        case.release["sealed_keys"] = []
    else:
        public = (
            Ed25519PrivateKey.generate().public_key()
            if change == "signer"
            else X25519PrivateKey.generate().public_key()
        )
        _write(
            case.root / ("configuration.pem" if change == "signer" else "installation.pem"),
            public.public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            ),
        )
    _write(case.root / "release.json", case.release)
    _refused(case.run("verify", "--package", package, "--initial-revision"))


@pytest.mark.parametrize(
    "content",
    [
        b'{"revision_id":"a","revision_id":"b"}',
        b"[]",
        b"\xff",
        b'{"a":NaN}',
        b'{"unexpected":"private-identifier"}',
        b"",
        b"x" * (1024 * 1024 + 1),
    ],
    ids=["duplicate", "array", "invalid-utf8", "nonfinite", "unknown", "empty", "oversized"],
)
def test_actual_cli_rejects_malformed_private_input(case: Case, content: bytes) -> None:
    _write(case.root / "source.json", content)
    destination = case.root / "no-artifact.json"
    _refused(case.run("build", "--destination", destination, "--initial-revision"))
    assert not destination.exists()


@pytest.mark.parametrize(
    "change",
    [
        "secret",
        "missing-override",
        "unknown",
        "authority",
        "revision",
        "shape",
        "sealed-public",
        "sealed-mismatch",
        "changed-retry",
    ],
)
def test_actual_cli_rejects_invalid_configuration(case: Case, change: str) -> None:
    history = (case.build("first.json"),) if change == "changed-retry" else ()
    if change == "secret":
        case.source["sealed"] = {"endpoint": {"password": "private-identifier"}}
    elif change == "missing-override":
        case.source["entity_overrides"] = []
    elif change == "unknown":
        case.source["environment"] = {"unknown": "private-identifier"}
    elif change == "authority":
        case.release["configuration_schema"] = {
            "mode": {"x-fdai-axis": "authority", "x-fdai-owner": "customer"}
        }
    elif change == "revision":
        case.source["revision_id"] = "short"
    elif change == "shape":
        case.source["entity_overrides"] = {}
    elif change == "sealed-public":
        case.source["environment"] = {"endpoint": "private-identifier"}
    elif change == "sealed-mismatch":
        case.source["sealed"] = {}
    else:
        case.source["environment"] = {"credential_ref": "different-ref"}
    _write(case.root / "source.json", case.source)
    _write(case.root / "release.json", case.release)
    destination = case.root / "no-artifact.json"
    _refused(case.run("build", "--destination", destination, *case.chain(history)))
    assert not destination.exists()
    if change == "secret":
        _write(destination, b"preserved existing output")
        _refused(case.run("build", "--destination", destination, *case.chain(history)))
        assert destination.read_bytes() == b"preserved existing output"


@pytest.mark.parametrize(
    "field,value",
    [
        ("release_version", 5),
        ("sealed_keys", ["endpoint", "endpoint"]),
        ("sealed_keys", [False]),
        ("sealed_keys", {}),
        ("configuration_schema", []),
    ],
)
def test_actual_cli_rejects_malformed_release_inputs(case: Case, field: str, value: object) -> None:
    case.release[field] = value
    _write(case.root / "release.json", case.release)
    destination = case.root / "no-artifact.json"
    _refused(case.run("build", "--destination", destination, "--initial-revision"))
    assert not destination.exists()


@pytest.mark.parametrize(
    "change",
    [
        "permissions",
        "parent",
        "symlink",
        "hardlink",
        "fifo",
        "relative",
        "output-symlink",
        "wrong-key-type",
        "mismatched-private-key",
        "invalid-pem",
    ],
)
def test_actual_cli_private_io_boundary(case: Case, change: str) -> None:
    source = case.root / "source.json"
    destination = case.root / "no-artifact.json"
    if change == "permissions":
        source.chmod(0o644)
    elif change == "parent":
        case.root.chmod(0o755)
    elif change in {"symlink", "hardlink", "fifo"}:
        original = case.root / "original.json"
        source.rename(original)
        if change == "symlink":
            source.symlink_to(original)
        elif change == "hardlink":
            os.link(original, source)
        else:
            os.mkfifo(source, 0o600)
    elif change == "relative":
        result = case.run(
            "build", "--input", "relative.json", "--destination", destination, "--initial-revision"
        )
        _refused(result)
        return
    elif change == "output-symlink":
        destination.symlink_to(source)
    elif change == "wrong-key-type":
        _write(
            case.root / "installation.pem",
            case.signing.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            ),
        )
    elif change == "mismatched-private-key":
        _write(
            case.root / "signing.pem",
            Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
    else:
        _write(case.root / "signing.pem", b"private-identifier-invalid-pem")
    before = source.read_bytes() if change == "output-symlink" else None
    _refused(case.run("build", "--destination", destination, "--initial-revision"))
    if before is not None:
        assert source.read_bytes() == before
    else:
        assert not destination.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ("configuration",),
        ("configuration", "build", "--help"),
        ("configuration", "verify", "--help"),
    ],
)
def test_actual_cli_help_without_inputs(case: Case, arguments: tuple[str, ...]) -> None:
    result = case.invoke(*arguments)
    assert result.returncode == 0, result.stderr
    assert "configuration" in result.stdout
    assert not result.stderr


def test_actual_cli_requires_explicit_chain_and_paths(case: Case) -> None:
    result = case.run("build", "--destination", case.root / "absent.json")
    assert result.returncode == 2
    assert not (case.root / "absent.json").exists()
    assert "--initial-revision" in result.stderr
