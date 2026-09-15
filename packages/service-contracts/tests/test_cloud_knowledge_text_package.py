"""Normalized-only transport and exact legacy compatibility, using synthetic signing material."""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from fdai_service_contracts.cloud_knowledge import canonical_bytes, content_digest
from fdai_service_contracts.cloud_knowledge_package import (
    KnowledgePackageError,
    assemble_signed_release,
    sign_release,
)
from fdai_service_contracts.cloud_knowledge_release import (
    CloudKnowledgeTextDocument,
    KnowledgeTextReleaseManifest,
    normalized_document,
    parse_knowledge_manifest,
)


def _load_helpers() -> ModuleType:
    """Reuse checkout-local fixtures under pytest importlib mode, without import-order dependence."""
    path = Path(__file__).with_name("test_cloud_knowledge_package.py")
    spec = importlib.util.spec_from_file_location("_cloud_text_package_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_HELPERS = _load_helpers()
case = _HELPERS.case
KEY_ID = _HELPERS.KEY_ID
_collected_document = _HELPERS._collected_document
_json_bytes = _HELPERS._json_bytes
_legacy_manifest = _HELPERS._legacy_manifest
_legacy_package = _HELPERS._legacy_package
_resign = _HELPERS._resign
_verify = _HELPERS._verify
_wire = _HELPERS._wire


def test_legacy_canonical_layout_and_signature_are_preserved(case: Any) -> None:
    legacy = _legacy_manifest(case)
    # Captured from the pre-change v1 implementation with this exact deterministic fixture.
    assert legacy.digest == "7f2dd5c44298f1576427f0065cec93cfc1c895aab0920266f26c803bf2a0915e"
    assert len(canonical_bytes(legacy)) == 2833
    sealed = _legacy_package(case)
    verified = _verify(case, sealed)
    assert verified.manifest == legacy
    assert verified.content == canonical_bytes(legacy)
    assert verified.binding.manifest_digest == legacy.digest
    assert parse_knowledge_manifest(verified.content) == legacy
    assert verified.binding.sources == tuple(document.evidence for document in legacy.documents)


@pytest.mark.parametrize("fault", ["v2_envelope", "original_hash"])
def test_legacy_rejects_relabeling_and_original_tamper(case: Any, fault: str) -> None:
    wire = json.loads(_legacy_package(case))
    if fault == "v2_envelope":
        wire["schema_version"] = "fdai.cloud-knowledge-package.v2"
    else:
        wire["manifest"]["documents"][0]["original_text"] = "tampered legacy body"
    with pytest.raises(KnowledgePackageError, match="closed"):
        _verify(case, _resign(case, wire))


@pytest.mark.parametrize("operation", ["sign", "assemble"])
def test_emitters_refuse_legacy_instead_of_stripping_signed_fields(
    case: Any, operation: str
) -> None:
    legacy = cast(KnowledgeTextReleaseManifest, _legacy_manifest(case))
    with pytest.raises(KnowledgePackageError, match="valid|v2"):
        if operation == "sign":
            sign_release(legacy, key_id=KEY_ID, private_key=case.private_key)
        else:
            assemble_signed_release(legacy, key_id=KEY_ID, signature=b"s" * 64)


@pytest.mark.parametrize("original", [None, "", "synthetic-original-body"])
def test_even_resigned_v2_original_fields_are_rejected(case: Any, original: str | None) -> None:
    wire = _wire(case)
    wire["manifest"]["documents"][0]["original_text"] = original
    with pytest.raises(KnowledgePackageError, match="closed"):
        _verify(case, _resign(case, wire))


@pytest.mark.parametrize("kind", ["envelope", "manifest", "reader", "normalized_hash"])
def test_version_downgrades_and_invalid_text_fail_even_with_valid_signature(
    case: Any, kind: str
) -> None:
    wire = _wire(case)
    if kind == "envelope":
        wire["schema_version"] = "fdai.cloud-knowledge-package.v1"
    elif kind == "manifest":
        wire["manifest"]["schema_version"] = "fdai.cloud-knowledge.v1"
    elif kind == "reader":
        wire["manifest"]["reader_version"] = "1.0.0"
    else:
        wire["manifest"]["documents"][0]["text"] += " altered"
    with pytest.raises(KnowledgePackageError, match="closed"):
        _verify(case, _resign(case, wire))


def test_projection_checks_original_before_omitting_it_and_keeps_exact_evidence(case: Any) -> None:
    original = _collected_document(case.registry.sources[0])
    before = canonical_bytes(original)
    projected = normalized_document(original)
    assert isinstance(projected, CloudKnowledgeTextDocument)
    assert set(projected.model_dump()) == {"evidence", "title", "text", "normalizer_version"}
    assert projected.evidence == original.evidence
    assert projected.text == original.text
    assert canonical_bytes(original) == before
    with pytest.raises(ValueError, match="hash"):
        normalized_document(original.model_copy(update={"original_text": "tampered original"}))
    with pytest.raises(ValueError, match="hash"):
        normalized_document(projected.model_copy(update={"text": "tampered normalized text"}))


def test_absent_original_hash_is_signed_provenance_not_receiver_byte_verification(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("verification must not fetch the omitted original")

    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    wire = _wire(case)
    evidence = wire["manifest"]["documents"][0]["evidence"]
    evidence["source_sha256"] = evidence["check"]["content_sha256"] = "e" * 64
    # Without a new signature, replacing the producer's original-hash assertion is tampering.
    wire["manifest_digest"] = content_digest(_json_bytes(wire["manifest"]))
    with pytest.raises(KnowledgePackageError, match="signature"):
        _verify(case, _json_bytes(wire))
    # A legitimate signer can attest another original. No absent-body equality is claimed.
    verified = _verify(case, _resign(case, wire))
    assert verified.binding.sources[0].source_sha256 == "e" * 64
    assert verified.manifest.documents[0].text == case.manifest.documents[0].text
