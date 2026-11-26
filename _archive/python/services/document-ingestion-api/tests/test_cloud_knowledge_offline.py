"""Offline CLI proofs with process-local signing material and temporary trust inputs.

These tests exercise the real argv entry point and codec, not production trust
bootstrap, document admission, or activation. Private keys never leave the process.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import stat
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn
from unittest.mock import Mock

import pytest
from fdai_ingestion_api_service.cloud_knowledge import __main__ as cli
from fdai_service_contracts.cloud_knowledge import canonical_bytes, content_digest
from fdai_service_contracts.cloud_knowledge_release import KnowledgeTextReleaseManifest

SIGNATURE_DOMAIN = b"fdai.cloud-knowledge.release.v1\x00"


def _load_package_helpers() -> ModuleType:
    """Reuse the same checkout-owned synthetic fixture as the API intake tests."""
    path = (
        Path(__file__).parents[3]
        / "packages/service-contracts/tests/test_cloud_knowledge_package.py"
    )
    spec = importlib.util.spec_from_file_location("_cloud_offline_package_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_PACKAGE_HELPERS = _load_package_helpers()
package_case = _PACKAGE_HELPERS.case


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


@pytest.fixture(autouse=True)
def _no_external_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail even if a rejected CLI invocation tries to swallow a network exception."""
    attempts: list[str] = []

    def deny(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("network")
        raise AssertionError("offline CLI must not use sockets or DNS")

    for name in (
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "gethostbyaddr",
        "getnameinfo",
        "create_connection",
    ):
        monkeypatch.setattr(socket, name, deny)
    for name in ("connect", "connect_ex", "send", "sendall", "sendto", "sendmsg"):
        monkeypatch.setattr(socket.socket, name, deny)
    yield
    assert attempts == []


@dataclass(frozen=True)
class _OfflineInputs:
    directory: Path
    manifest: KnowledgeTextReleaseManifest = field(repr=False)
    manifest_bytes: bytes = field(repr=False)
    package_bytes: bytes = field(repr=False)

    def argv(self, operation: str) -> list[str]:
        source = "package.json" if operation == "inspect" else "manifest.json"
        args = [
            operation,
            "--input",
            str(self.directory / source),
            "--registry",
            str(self.directory / "registry.json"),
            "--trust",
            str(self.directory / "trust.json"),
        ]
        if operation == "assemble":
            args.extend(
                [
                    "--signature",
                    str(self.directory / "signature.bin"),
                    "--key-id",
                    _PACKAGE_HELPERS.KEY_ID,
                    "--output",
                    str(self.directory / "assembled.json"),
                ]
            )
        return args


@pytest.fixture
def offline(package_case: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _OfflineInputs:
    """Sign independently of the production assembler, using only the synthetic fixture key."""
    manifest_bytes = _json_bytes(package_case.manifest.model_dump(mode="json"))
    assert manifest_bytes == canonical_bytes(package_case.manifest)
    signature = package_case.private_key.sign(SIGNATURE_DOMAIN + manifest_bytes)
    package_bytes = _json_bytes(
        {
            "schema_version": "fdai.cloud-knowledge-package.v2",
            "purpose": "fdai.cloud-knowledge.release.v1",
            "algorithm": "Ed25519",
            "key_id": _PACKAGE_HELPERS.KEY_ID,
            "manifest_digest": content_digest(manifest_bytes),
            "manifest": json.loads(manifest_bytes),
            "signature": signature.hex(),
        }
    )
    for name, content in (
        ("registry.json", canonical_bytes(package_case.registry)),
        ("trust.json", canonical_bytes(package_case.trust)),
        ("manifest.json", manifest_bytes),
        ("signature.bin", signature),
        ("package.json", package_bytes),
    ):
        (tmp_path / name).write_bytes(content)
    monkeypatch.setattr(cli, "datetime", Mock(now=Mock(return_value=_PACKAGE_HELPERS.NOW)))
    return _OfflineInputs(tmp_path, package_case.manifest, manifest_bytes, package_bytes)


def _assert_report(
    capsys: pytest.CaptureFixture[str], manifest: KnowledgeTextReleaseManifest | None = None
) -> None:
    """Only the content-free result contract may cross stdout or stderr."""
    output = capsys.readouterr()
    expected = (
        {"status": "rejected", "reason": "invalid_package_or_trust_inputs"}
        if manifest is None
        else {
            "status": "verified_candidate",
            "release_id": manifest.release_id,
            "manifest_digest": manifest.digest,
            "approval_required": True,
        }
    )
    assert output.err == ""
    assert output.out.count("\n") == 1
    assert json.loads(output.out) == expected


def _input_digests(directory: Path) -> dict[str, str]:
    return {path.name: content_digest(path.read_bytes()) for path in directory.iterdir()}


def test_inspect_verifies_exact_signed_bytes_without_writes(
    offline: _OfflineInputs, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _input_digests(offline.directory)
    args = offline.argv("inspect") + ["--output", str(offline.directory / "unused.json")]

    assert cli.main(args) == 0

    _assert_report(capsys, offline.manifest)
    assert _input_digests(offline.directory) == before


def test_assemble_preserves_detached_signature_and_exact_canonical_manifest(
    offline: _OfflineInputs, package_case: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _input_digests(offline.directory)

    assert cli.main(offline.argv("assemble")) == 0

    _assert_report(capsys, offline.manifest)
    output = offline.directory / "assembled.json"
    assert output.read_bytes() == offline.package_bytes
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    wire = json.loads(output.read_bytes())
    assert all("original_text" not in document for document in wire["manifest"]["documents"])
    signed_bytes = _json_bytes(wire["manifest"])
    assert signed_bytes == offline.manifest_bytes
    signature = bytes.fromhex(wire["signature"])
    assert signature == (offline.directory / "signature.bin").read_bytes()
    package_case.private_key.public_key().verify(signature, SIGNATURE_DOMAIN + signed_bytes)
    after = _input_digests(offline.directory)
    assert after.pop("assembled.json") == content_digest(offline.package_bytes)
    assert after == before
    args = offline.argv("inspect")
    args[args.index("--input") + 1] = str(output)
    assert cli.main(args) == 0
    _assert_report(capsys, offline.manifest)


@pytest.mark.parametrize("destination", ["file", "symlink", "manifest"])
def test_assemble_never_overwrites_an_existing_destination(
    offline: _OfflineInputs, capsys: pytest.CaptureFixture[str], destination: str
) -> None:
    output = offline.directory / "assembled.json"
    retained = offline.directory / "manifest.json"
    if destination == "file":
        output.write_bytes(b"existing synthetic output")
        retained = output
    elif destination == "symlink":
        output.symlink_to(retained)
    else:
        output = retained
    original = retained.read_bytes()
    args = offline.argv("assemble")
    args[args.index("--output") + 1] = str(output)

    assert cli.main(args) == 1

    _assert_report(capsys)
    assert retained.read_bytes() == original
    assert output.is_symlink() is (destination == "symlink")


@pytest.mark.parametrize("operation", ["inspect", "assemble"])
@pytest.mark.parametrize("fault", ["signature", "wrong_domain", "missing_separator", "manifest"])
def test_invalid_signatures_fail_closed_without_output(
    offline: _OfflineInputs,
    package_case: Any,
    capsys: pytest.CaptureFixture[str],
    operation: str,
    fault: str,
) -> None:
    wire = json.loads(offline.package_bytes)
    if fault == "manifest":
        wire["manifest"]["release_id"] = "changed-release"
        wire["manifest_digest"] = content_digest(_json_bytes(wire["manifest"]))
    elif fault == "signature":
        signature = bytes.fromhex(wire["signature"])
        wire["signature"] = (bytes([signature[0] ^ 1]) + signature[1:]).hex()
    else:
        domain = b"fdai.application.v1\x00" if fault == "wrong_domain" else SIGNATURE_DOMAIN[:-1]
        wire["signature"] = package_case.private_key.sign(domain + offline.manifest_bytes).hex()
    (offline.directory / "package.json").write_bytes(_json_bytes(wire))
    (offline.directory / "manifest.json").write_bytes(_json_bytes(wire["manifest"]))
    (offline.directory / "signature.bin").write_bytes(bytes.fromhex(wire["signature"]))

    assert cli.main(offline.argv(operation)) == 1

    _assert_report(capsys)
    assert not (offline.directory / "assembled.json").exists()


def test_inspect_rejects_noncanonical_transport_even_with_valid_inner_signature(
    offline: _OfflineInputs, capsys: pytest.CaptureFixture[str]
) -> None:
    (offline.directory / "package.json").write_bytes(offline.package_bytes + b"\n")
    assert cli.main(offline.argv("inspect")) == 1
    _assert_report(capsys)


@pytest.mark.parametrize("operation", ["inspect", "assemble"])
def test_legacy_is_inspectable_but_cannot_be_newly_assembled(
    offline: _OfflineInputs, package_case: Any, capsys: pytest.CaptureFixture[str], operation: str
) -> None:
    legacy = _PACKAGE_HELPERS._legacy_manifest(package_case)
    (offline.directory / "package.json").write_bytes(_PACKAGE_HELPERS._legacy_package(package_case))
    content = canonical_bytes(legacy)
    (offline.directory / "manifest.json").write_bytes(content)
    (offline.directory / "signature.bin").write_bytes(
        package_case.private_key.sign(SIGNATURE_DOMAIN + content)
    )
    before = _input_digests(offline.directory)
    assert cli.main(offline.argv(operation)) == (0 if operation == "inspect" else 1)
    if operation == "inspect":
        output = json.loads(capsys.readouterr().out)
        assert output["manifest_digest"] == legacy.digest
    else:
        _assert_report(capsys)
    assert _input_digests(offline.directory) == before


def test_assembly_requires_canonical_manifest_input_without_silent_rewriting(
    offline: _OfflineInputs, capsys: pytest.CaptureFixture[str]
) -> None:
    (offline.directory / "manifest.json").write_bytes(offline.manifest_bytes + b"\n")
    assert cli.main(offline.argv("assemble")) == 1
    _assert_report(capsys)
    assert not (offline.directory / "assembled.json").exists()


@pytest.mark.parametrize(
    ("operation", "option"),
    [
        (operation, option)
        for operation in ("inspect", "assemble")
        for option in ("input", "registry", "trust")
    ]
    + [("assemble", "signature")],
)
@pytest.mark.parametrize("fault", ["symlink", "oversize"])
def test_cli_refuses_linked_or_oversize_inputs_before_writing(
    offline: _OfflineInputs,
    capsys: pytest.CaptureFixture[str],
    operation: str,
    option: str,
    fault: str,
) -> None:
    args = offline.argv(operation)
    position = args.index(f"--{option}") + 1
    original = Path(args[position])
    original_digest = content_digest(original.read_bytes())
    rejected = offline.directory / "rejected-input"
    if fault == "symlink":
        rejected.symlink_to(original)
    else:
        maximum = {"input": cli.MAX_PACKAGE_BYTES, "signature": 64}.get(option, 1024 * 1024)
        # A sparse regular file exercises the actual fstat bound without a large allocation.
        with rejected.open("xb") as stream:
            stream.truncate(maximum + 1)
    args[position] = str(rejected)

    assert cli.main(args) == 1

    _assert_report(capsys)
    assert content_digest(original.read_bytes()) == original_digest
    assert not (offline.directory / "assembled.json").exists()
