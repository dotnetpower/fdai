"""Synthetic, no-I/O package proofs; signatures never renew source dates or grant authority."""

from __future__ import annotations

import base64
import json
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from fdai_service_contracts import cloud_knowledge_package as package_codec
from fdai_service_contracts.cloud_knowledge import (
    Applicability,
    CloudKnowledgeSource,
    CloudSourceEvidence,
    Freshness,
    SourceCheckReceipt,
    SourceRegistryRevision,
    canonical_bytes,
    content_digest,
)
from fdai_service_contracts.cloud_knowledge_package import (
    MAX_PACKAGE_BYTES,
    PACKAGE_PURPOSE,
    KnowledgePackageError,
    KnowledgeTrustedKey,
    KnowledgeTrustPolicy,
    VerifiedKnowledgePackage,
    sign_release,
    verify_package,
)
from fdai_service_contracts.cloud_knowledge_release import (
    CloudKnowledgeDocument,
    KnowledgeReleaseManifest,
)

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
SOURCE_TIME = NOW - timedelta(days=1)
KEY_ID = "synthetic-release-key"


@dataclass(frozen=True)
class _Case:
    manifest: KnowledgeReleaseManifest
    registry: SourceRegistryRevision
    trust: KnowledgeTrustPolicy
    private_key: Ed25519PrivateKey


def _document(
    source: CloudKnowledgeSource, *, at: datetime = SOURCE_TIME
) -> CloudKnowledgeDocument:
    original = f"Original reference: {source.source_id}. 예제."
    text = f"Reference: {source.source_id}. 예제."
    digest = content_digest(original.encode("utf-8"))
    return CloudKnowledgeDocument(
        title=source.title,
        original_text=original,
        text=text,
        evidence=CloudSourceEvidence(
            source_id=source.source_id,
            source_url=source.url,
            source_sha256=digest,
            normalized_sha256=content_digest(text.encode("utf-8")),
            collected_at=at,
            source_updated_at=at - timedelta(days=1),
            check=SourceCheckReceipt(
                source_id=source.source_id,
                source_url=source.url,
                checked_at=at + timedelta(hours=1),
                outcome="fetched",
                content_sha256=digest,
                equivalence="body_hash",
                collector_id="synthetic-collector",
            ),
            applicability=source.applicability,
            policy=source.policy,
            license_ref=source.license_ref,
        ),
    )


@pytest.fixture
def case() -> _Case:
    private_key = Ed25519PrivateKey.generate()
    registry = SourceRegistryRevision(
        revision=1,
        approved_by="source-reviewer",
        valid_until=NOW + timedelta(days=14),
        sources=tuple(
            CloudKnowledgeSource(
                source_id=source_id,
                collection_id="reference" if source_id != "foreign" else "another-collection",
                url=f"https://example.com/reference/{source_id}",
                title=f"Reference {source_id}",
                applicability=Applicability(
                    resource_type="Microsoft.ApiManagement/service", service_generation="classic"
                ),
                storage_allowed=True,
                internal_transfer_allowed=True,
                license_ref="synthetic-license",
                max_bytes=1024,
            )
            for source_id in ("source-a", "source-b", "foreign")
        ),
    )
    return _Case(
        manifest=KnowledgeReleaseManifest(
            release_id="release-1",
            sequence=1,
            collection_id="reference",
            registry_digest=registry.digest,
            package_created_at=NOW - timedelta(minutes=5),
            expires_at=NOW + timedelta(days=7),
            documents=tuple(_document(source) for source in registry.sources[:2]),
        ),
        registry=registry,
        trust=KnowledgeTrustPolicy(
            approved_by="trust-reviewer",
            valid_from=NOW - timedelta(days=2),
            valid_until=NOW + timedelta(days=10),
            keys=(
                KnowledgeTrustedKey(
                    key_id=KEY_ID,
                    public_key=private_key.public_key().public_bytes_raw().hex(),
                    valid_from=NOW - timedelta(days=10),
                    valid_until=NOW + timedelta(days=10),
                ),
            ),
            revocation_checked_at=NOW - timedelta(minutes=1),
            revocation_max_age_seconds=3600,
        ),
        private_key=private_key,
    )


def _sign(case: _Case) -> bytes:
    return sign_release(case.manifest, key_id=KEY_ID, private_key=case.private_key)


def test_detached_signature_assembly_matches_signer_and_rejects_wrong_length(case: _Case) -> None:
    signature = case.private_key.sign(
        PACKAGE_PURPOSE.encode("ascii") + b"\x00" + canonical_bytes(case.manifest)
    )
    assembled = package_codec.assemble_signed_release(
        case.manifest, key_id=KEY_ID, signature=signature
    )
    assert assembled == _sign(case)
    assert _verify(case, assembled).manifest == case.manifest
    with pytest.raises(KnowledgePackageError, match="64 bytes"):
        package_codec.assemble_signed_release(case.manifest, key_id=KEY_ID, signature=b"invalid")


def _with_registry(case: _Case, registry: SourceRegistryRevision) -> _Case:
    return replace(
        case,
        registry=registry,
        manifest=case.manifest.model_copy(update={"registry_digest": registry.digest}),
    )


def _verify(
    case: _Case,
    content: bytes | None = None,
    *,
    now: datetime = NOW,
    max_bytes: int = MAX_PACKAGE_BYTES,
    minimum_sequence: int = 0,
) -> VerifiedKnowledgePackage:
    return verify_package(
        _sign(case) if content is None else content,
        registry=case.registry,
        trust=case.trust,
        now=now,
        max_bytes=max_bytes,
        minimum_sequence=minimum_sequence,
    )


def _wire(case: _Case) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_sign(case)))


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _resign(case: _Case, wire: dict[str, Any]) -> bytes:
    """Create signed malicious wire data without depending on the production signer's checks."""
    manifest = _json_bytes(wire["manifest"])
    wire["manifest_digest"] = content_digest(manifest)
    signed = case.private_key.sign(PACKAGE_PURPOSE.encode("ascii") + b"\x00" + manifest)
    wire["signature"] = signed.hex()
    return _json_bytes(wire)


@pytest.mark.parametrize("encoding", ["hex", "uppercase_hex", "base64"])
def test_valid_package_preserves_exact_manifest_and_advisory_binding(
    case: _Case, encoding: str
) -> None:
    public = case.private_key.public_key().public_bytes_raw()
    encoded = {
        "hex": public.hex(),
        "uppercase_hex": public.hex().upper(),
        "base64": base64.b64encode(public).decode("ascii"),
    }[encoding]
    key = case.trust.keys[0].model_copy(update={"public_key": encoded})
    case = replace(case, trust=case.trust.model_copy(update={"keys": (key,)}))
    sealed = _sign(case)
    result = _verify(case, sealed)
    assert sealed == _sign(case)
    assert result.manifest == case.manifest
    assert result.content == canonical_bytes(case.manifest)
    assert result.binding.manifest_digest == content_digest(result.content) == case.manifest.digest
    assert result.binding.registry_digest == case.registry.digest
    assert result.binding.imported_at == NOW
    assert result.binding.package_created_at == case.manifest.package_created_at
    assert result.binding.sources == tuple(doc.evidence for doc in case.manifest.documents)
    assert result.binding.verified_key_id == KEY_ID
    assert result.binding.rollback_of is None
    assert repr(result) == "VerifiedKnowledgePackage()"
    with pytest.raises(FrozenInstanceError):
        result.__setattr__("content", b"replacement")
    wire = _wire(case)
    assert set(wire) == {
        "algorithm",
        "schema_version",
        "purpose",
        "key_id",
        "manifest_digest",
        "manifest",
        "signature",
    }
    case.private_key.public_key().verify(
        bytes.fromhex(wire["signature"]),
        b"fdai.cloud-knowledge.release.v1\x00" + result.content,
    )


@pytest.mark.parametrize("field", ["manifest", "signature", "manifest_digest"])
def test_manifest_and_signature_tampering_is_rejected(case: _Case, field: str) -> None:
    wire = _wire(case)
    if field == "manifest":
        wire["manifest"]["release_id"] = "altered-release"
        wire["manifest_digest"] = content_digest(_json_bytes(wire["manifest"]))
    else:
        wire[field] = "0" * (128 if field == "signature" else 64)
    with pytest.raises(KnowledgePackageError, match="signature|digest"):
        _verify(case, _json_bytes(wire))


@pytest.mark.parametrize("kind", ["unapproved", "wrong_key", "revoked", "substituted_key_id"])
def test_unapproved_wrong_or_revoked_key_is_rejected(case: _Case, kind: str) -> None:
    wire = _wire(case)
    if kind == "unapproved":
        wire["key_id"] = "unapproved-key"
    elif kind == "revoked":
        case = replace(case, trust=case.trust.model_copy(update={"revoked_key_ids": (KEY_ID,)}))
    else:
        other = Ed25519PrivateKey.generate()
        if kind == "wrong_key":
            wire["signature"] = other.sign(
                PACKAGE_PURPOSE.encode("ascii") + b"\x00" + canonical_bytes(case.manifest)
            ).hex()
        else:
            key = case.trust.keys[0].model_copy(
                update={
                    "key_id": "another-key",
                    "public_key": other.public_key().public_bytes_raw().hex(),
                }
            )
            case = replace(
                case, trust=case.trust.model_copy(update={"keys": (*case.trust.keys, key)})
            )
            wire["key_id"] = key.key_id
    with pytest.raises(KnowledgePackageError, match="key|signature"):
        _verify(case, _json_bytes(wire))


@pytest.mark.parametrize(
    "domain", [b"", b"fdai.application.v1\x00", PACKAGE_PURPOSE.encode("ascii")]
)
def test_wrong_purpose_signature_is_rejected(case: _Case, domain: bytes) -> None:
    wire = _wire(case)
    wire["signature"] = case.private_key.sign(domain + canonical_bytes(case.manifest)).hex()
    with pytest.raises(KnowledgePackageError, match="signature"):
        _verify(case, _json_bytes(wire))


@pytest.mark.parametrize("key", ["purpose", "release_id", "source_url", "license_ref", "policy_id"])
def test_duplicate_json_keys_are_rejected_at_every_depth(case: _Case, key: str) -> None:
    token = _json_bytes(key) + b":"
    duplicate = _sign(case).replace(token, token + b"null," + token, 1)
    with pytest.raises(KnowledgePackageError, match="duplicate"):
        _verify(case, duplicate)


def test_escaped_duplicate_key_is_rejected(case: _Case) -> None:
    content = _sign(case).replace(b'"purpose":', b'"purpose":null,"\\u0070urpose":', 1)
    with pytest.raises(KnowledgePackageError, match="duplicate"):
        _verify(case, content)


@pytest.mark.parametrize(
    "kind",
    [
        "nested_whitespace",
        "missing_default",
        "epoch_timestamp",
        "escaped_unicode",
        "reordered_keys",
        "trailing_newline",
    ],
)
def test_noncanonical_manifest_representations_are_rejected(case: _Case, kind: str) -> None:
    wire = _wire(case)
    content = _sign(case)
    if kind == "nested_whitespace":
        content = content.replace(b'"documents":[', b'"documents": [', 1)
    elif kind == "missing_default":
        del wire["manifest"]["reader_version"]
        content = _json_bytes(wire)
    elif kind == "epoch_timestamp":
        wire["manifest"]["package_created_at"] = int(case.manifest.package_created_at.timestamp())
        content = _json_bytes(wire)
    elif kind == "escaped_unicode":
        content = json.dumps(wire, sort_keys=True, separators=(",", ":")).encode("utf-8")
    elif kind == "reordered_keys":
        content = json.dumps(
            dict(reversed(wire.items())), separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    else:
        content += b"\n"
    with pytest.raises(KnowledgePackageError, match="canonical"):
        _verify(case, content)


@pytest.mark.parametrize(
    "field",
    [
        "public_key",
        "trust",
        "files",
        "archive",
        "executable",
        "sql",
        "embeddings",
        "model_weights",
        "grant_authority",
    ],
)
def test_package_cannot_supply_trust_or_non_document_artifacts(case: _Case, field: str) -> None:
    wire = _wire(case)
    wire[field] = []
    with pytest.raises(KnowledgePackageError, match="closed"):
        _verify(case, _json_bytes(wire))


@pytest.mark.parametrize(
    "path",
    [
        ("manifest",),
        ("manifest", "documents", 0),
        ("manifest", "documents", 0, "evidence"),
        ("manifest", "documents", 0, "evidence", "check"),
        ("manifest", "documents", 0, "evidence", "policy"),
        ("manifest", "documents", 0, "evidence", "applicability"),
    ],
)
def test_unknown_nested_fields_are_rejected(case: _Case, path: tuple[str | int, ...]) -> None:
    wire = _wire(case)
    nested: Any = wire
    for part in path:
        nested = nested[part]
    nested["grant_authority"] = True
    with pytest.raises(KnowledgePackageError, match="closed"):
        _verify(case, _resign(case, wire))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", "fdai.application.v1"),
        ("algorithm", "none"),
        ("schema_version", "fdai.cloud-knowledge-package.v2"),
    ],
)
def test_unsupported_envelope_metadata_is_rejected(case: _Case, field: str, value: str) -> None:
    wire = _wire(case)
    wire[field] = value
    with pytest.raises(KnowledgePackageError, match="closed"):
        _verify(case, _json_bytes(wire))


@pytest.mark.parametrize("number", [b"NaN", b"Infinity", b"-Infinity", b"1e309", b"1.0", b"true"])
def test_nonfinite_and_noninteger_json_numbers_are_rejected(case: _Case, number: bytes) -> None:
    content = _sign(case).replace(b'"sequence":1', b'"sequence":' + number, 1)
    with pytest.raises(KnowledgePackageError):
        _verify(case, content)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\xff",
        b"[]",
        b"{}",
        b"PK\x03\x04",
        b"\xef\xbb\xbf{}",
        b'"\\ud800"',
        b"[" * 1200 + b"0" + b"]" * 1200,
    ],
)
def test_invalid_utf8_archives_and_malformed_json_are_rejected(case: _Case, content: bytes) -> None:
    with pytest.raises(KnowledgePackageError):
        _verify(case, content)


def test_exact_byte_limit_accepts_only_complete_bounded_content(case: _Case) -> None:
    content = _sign(case)
    assert _verify(case, content, max_bytes=len(content)).manifest == case.manifest
    with pytest.raises(KnowledgePackageError, match="byte limit"):
        _verify(case, content, max_bytes=len(content) - 1)
    with pytest.raises(KnowledgePackageError, match="byte limit"):
        _verify(case, b" " * (MAX_PACKAGE_BYTES + 1))


@pytest.mark.parametrize("max_bytes", [0, -1, True, MAX_PACKAGE_BYTES + 1])
def test_byte_limit_configuration_cannot_widen_or_disable_bounds(
    case: _Case, max_bytes: int
) -> None:
    with pytest.raises(KnowledgePackageError, match="byte limit"):
        _verify(case, max_bytes=max_bytes)


@pytest.mark.parametrize("boundary", ["manifest", "envelope"])
def test_signer_enforces_both_byte_ceilings(
    case: _Case, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    limit = len(canonical_bytes(case.manifest) if boundary == "manifest" else _sign(case)) - 1
    monkeypatch.setattr(package_codec, "MAX_PACKAGE_BYTES", limit)
    with pytest.raises(KnowledgePackageError, match="byte limit"):
        _sign(case)


@pytest.mark.parametrize(
    "kind", ["registry_revision", "registry_digest", "missing_collection", "foreign_collection"]
)
def test_registry_revision_and_collection_are_exact(case: _Case, kind: str) -> None:
    wire = _wire(case)
    if kind == "registry_revision":
        case = replace(case, registry=case.registry.model_copy(update={"revision": 2}))
    elif kind == "registry_digest":
        wire["manifest"]["registry_digest"] = "f" * 64
    elif kind == "foreign_collection":
        wire["manifest"]["collection_id"] = "another-collection"
    else:
        wire["manifest"]["collection_id"] = "missing-collection"
    with pytest.raises(KnowledgePackageError, match="registry|collection"):
        _verify(case, _resign(case, wire))


@pytest.mark.parametrize("kind", ["foreign_source", "missing_source", "foreign_withdrawal"])
def test_complete_collection_coverage_cannot_be_narrowed_or_broadened(
    case: _Case, kind: str
) -> None:
    wire = _wire(case)
    if kind == "foreign_source":
        wire["manifest"]["documents"][0] = _document(case.registry.sources[2]).model_dump(
            mode="json"
        )
    else:
        wire["manifest"]["documents"].pop()
        if kind == "foreign_withdrawal":
            wire["manifest"].update(
                withdrawn_source_ids=["foreign"], withdrawal_evidence_ref="reviewed-withdrawal"
            )
    with pytest.raises(KnowledgePackageError, match="complete registered collection"):
        _verify(case, _resign(case, wire))


def test_reviewed_withdrawals_complete_the_selected_collection(case: _Case) -> None:
    wire = _wire(case)
    wire["manifest"]["documents"].pop()
    wire["manifest"].update(
        withdrawn_source_ids=["source-b"], withdrawal_evidence_ref="reviewed-withdrawal"
    )
    result = _verify(case, _resign(case, wire))
    assert result.manifest.withdrawn_source_ids == ("source-b",)
    assert len(result.binding.sources) == 1
    del wire["manifest"]["withdrawal_evidence_ref"]
    with pytest.raises(KnowledgePackageError):
        _verify(case, _resign(case, wire))


@pytest.mark.parametrize("field", ["url", "applicability", "policy", "license_ref", "title"])
def test_document_provenance_must_match_registered_source(case: _Case, field: str) -> None:
    wire = _wire(case)
    document = wire["manifest"]["documents"][0]
    evidence = document["evidence"]
    if field == "url":
        evidence["source_url"] = "https://example.com/another-origin-document"
        evidence["check"]["source_url"] = evidence["source_url"]
    elif field == "title":
        document["title"] = "Unreviewed title"
    elif field == "applicability":
        evidence["applicability"]["service_generation"] = "v2"
    elif field == "policy":
        evidence["policy"]["check_interval_seconds"] = 60
    else:
        evidence["license_ref"] = "different-license"
    with pytest.raises(KnowledgePackageError, match="provenance"):
        _verify(case, _resign(case, wire))


@pytest.mark.parametrize("right", ["storage_allowed", "internal_transfer_allowed"])
def test_full_text_requires_storage_and_internal_transfer_rights(case: _Case, right: str) -> None:
    source = case.registry.sources[0].model_copy(update={right: False})
    registry = case.registry.model_copy(update={"sources": (source, *case.registry.sources[1:])})
    case = _with_registry(case, registry)
    with pytest.raises(KnowledgePackageError, match="storage and internal transfer rights"):
        _verify(case)


def test_registered_source_limits_count_utf8_bytes_not_characters(case: _Case) -> None:
    source = case.registry.sources[0].model_copy(
        update={"max_bytes": len(case.manifest.documents[0].original_text)}
    )
    registry = case.registry.model_copy(update={"sources": (source, *case.registry.sources[1:])})
    case = _with_registry(case, registry)
    with pytest.raises(KnowledgePackageError, match="source byte limit"):
        _verify(case)


@pytest.mark.parametrize(
    "kind",
    [
        "registry_expired",
        "trust_expired",
        "trust_future",
        "key_expired",
        "key_future",
        "key_after_release",
        "package_expired",
        "package_future",
    ],
)
def test_expired_or_future_admission_metadata_is_rejected(case: _Case, kind: str) -> None:
    if kind == "registry_expired":
        case = replace(case, registry=case.registry.model_copy(update={"valid_until": NOW}))
    elif kind.startswith("trust_"):
        update = (
            {"valid_until": NOW}
            if kind.endswith("expired")
            else {"valid_from": NOW + timedelta(seconds=1)}
        )
        case = replace(case, trust=case.trust.model_copy(update=update))
    elif kind.startswith("key_"):
        start = NOW + timedelta(seconds=1) if kind == "key_future" else NOW - timedelta(minutes=4)
        update = {"valid_until": NOW} if kind == "key_expired" else {"valid_from": start}
        key = case.trust.keys[0].model_copy(update=update)
        case = replace(case, trust=case.trust.model_copy(update={"keys": (key,)}))
    else:
        update = (
            {"expires_at": NOW}
            if kind == "package_expired"
            else {"package_created_at": NOW + timedelta(seconds=1)}
        )
        case = replace(case, manifest=case.manifest.model_copy(update=update))
    with pytest.raises(KnowledgePackageError, match="expired|valid"):
        _verify(case)


@pytest.mark.parametrize("kind", ["stale", "future"])
def test_stale_or_future_revocation_evidence_is_rejected(case: _Case, kind: str) -> None:
    checked = NOW - timedelta(seconds=3600) if kind == "stale" else NOW + timedelta(microseconds=1)
    case = replace(case, trust=case.trust.model_copy(update={"revocation_checked_at": checked}))
    with pytest.raises(KnowledgePackageError, match="stale|future"):
        _verify(case)


@pytest.mark.parametrize("owner", ["registry", "trust", "key", "manifest", "revocation"])
def test_admission_expiry_is_the_earliest_independent_deadline(case: _Case, owner: str) -> None:
    expiry = NOW + timedelta(seconds=30)
    if owner == "registry":
        registry = case.registry.model_copy(update={"valid_until": expiry})
        case = _with_registry(case, registry)
    elif owner == "trust":
        case = replace(case, trust=case.trust.model_copy(update={"valid_until": expiry}))
    elif owner == "key":
        key = case.trust.keys[0].model_copy(update={"valid_until": expiry})
        case = replace(case, trust=case.trust.model_copy(update={"keys": (key,)}))
    elif owner == "manifest":
        case = replace(case, manifest=case.manifest.model_copy(update={"expires_at": expiry}))
    else:
        case = replace(case, trust=case.trust.model_copy(update={"revocation_max_age_seconds": 90}))
    assert _verify(case).binding.admission_expires_at == expiry
    with pytest.raises(KnowledgePackageError):
        _verify(case, now=expiry)


@pytest.mark.parametrize("days_old", [44, 90])
def test_old_source_dates_survive_new_packages_and_imports(case: _Case, days_old: int) -> None:
    documents = tuple(
        _document(source, at=NOW - timedelta(days=days_old)) for source in case.registry.sources[:2]
    )
    case = replace(case, manifest=case.manifest.model_copy(update={"documents": documents}))
    first = _verify(case)
    later = _verify(case, now=NOW + timedelta(minutes=1))
    assert first.content == later.content
    assert first.binding.imported_at < later.binding.imported_at
    assert (
        first.binding.sources == later.binding.sources == tuple(doc.evidence for doc in documents)
    )
    for original, imported in zip(documents, later.binding.sources, strict=True):
        assert imported.collected_at == original.evidence.collected_at
        assert imported.check.checked_at == original.evidence.check.checked_at
        assert imported.source_updated_at == original.evidence.source_updated_at
        assert imported.freshness(NOW) is Freshness.STALE
        assert not imported.allows_current_guidance(NOW)


@pytest.mark.parametrize(
    "kind", ["future_update", "update_after_collection", "backward_check", "future_check"]
)
def test_future_or_skewed_source_dates_are_rejected(case: _Case, kind: str) -> None:
    wire = _wire(case)
    evidence = wire["manifest"]["documents"][0]["evidence"]
    instant = NOW + timedelta(seconds=1)
    if kind == "update_after_collection":
        instant = NOW - timedelta(hours=12)
    elif kind == "backward_check":
        instant = NOW - timedelta(days=2)
    timestamp = instant.isoformat().replace("+00:00", "Z")
    if kind.endswith("check"):
        evidence["check"]["checked_at"] = timestamp
    else:
        evidence["source_updated_at"] = timestamp
    with pytest.raises(KnowledgePackageError):
        _verify(case, _resign(case, wire))


def test_naive_verification_clock_is_rejected(case: _Case) -> None:
    with pytest.raises(KnowledgePackageError, match="timezone-aware"):
        _verify(case, now=NOW.replace(tzinfo=None))


def test_sequence_floor_is_strict_and_verification_remains_stateless(case: _Case) -> None:
    assert _verify(case) == _verify(case)
    for minimum in (case.manifest.sequence, case.manifest.sequence + 1, -1, True):
        with pytest.raises(KnowledgePackageError, match="sequence"):
            _verify(case, minimum_sequence=minimum)


@pytest.mark.parametrize(
    "key", ["!" * 44, "00" * 31, "A" * 43, "-----BEGIN PUBLIC KEY-----" + "A" * 20]
)
def test_trust_accepts_only_raw_hex_or_canonical_base64_public_keys(case: _Case, key: str) -> None:
    with pytest.raises(ValidationError):
        KnowledgeTrustedKey.model_validate(case.trust.keys[0].model_dump() | {"public_key": key})


@pytest.mark.parametrize("kind", ["duplicate_id", "public_key_alias", "duplicate_revocation"])
def test_trust_key_and_revocation_identities_must_be_unambiguous(case: _Case, kind: str) -> None:
    data = case.trust.model_dump()
    if kind == "duplicate_revocation":
        data["revoked_key_ids"] = (KEY_ID, KEY_ID)
    else:
        alias = case.trust.keys[0].model_copy(
            update={
                "key_id": KEY_ID if kind == "duplicate_id" else "alias-key",
                "public_key": base64.b64encode(
                    case.private_key.public_key().public_bytes_raw()
                ).decode("ascii"),
            }
        )
        data["keys"] = (case.trust.keys[0].model_dump(), alias.model_dump())
    with pytest.raises(ValidationError, match="unique"):
        KnowledgeTrustPolicy.model_validate(data)


@pytest.mark.parametrize("field", ["approved_by", "revocation_checked_at"])
def test_independent_trust_requires_approval_and_revocation_evidence(
    case: _Case, field: str
) -> None:
    data = case.trust.model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        KnowledgeTrustPolicy.model_validate(data)
    if field == "approved_by":
        registry = case.registry.model_dump()
        del registry[field]
        with pytest.raises(ValidationError):
            SourceRegistryRevision.model_validate(registry)


def test_verification_errors_do_not_expose_document_content(
    case: _Case, capsys: pytest.CaptureFixture[str], recwarn: pytest.WarningsRecorder
) -> None:
    wire = _wire(case)
    marker = "synthetic-private-body-marker"
    wire["manifest"]["documents"][0]["original_text"] = marker
    with pytest.raises(KnowledgePackageError) as error:
        _verify(case, _resign(case, wire))
    assert marker not in str(error.value)
    assert error.value.__suppress_context__
    malformed = replace(case, trust=case.trust.model_copy(update={"approved_by": [marker]}))
    with pytest.raises(KnowledgePackageError) as trust_error:
        _verify(malformed)
    assert marker not in str(trust_error.value)
    assert not recwarn.list
    output = capsys.readouterr()
    assert output.out == output.err == ""
