"""Provider-neutral execution safeguard proof-bundle tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from fdai_service_contracts import SafeguardProofBundle as ExportedSafeguardProofBundle
from fdai_service_contracts.execution_safeguards import (
    SafeguardProof,
    SafeguardProofBundle,
    SafeguardProofKind,
)
from fdai_service_contracts.executor import (
    SafeguardProofBundle as ExecutorSafeguardProofBundle,
)
from fdai_service_contracts.executor_models import ExecutionPath
from fdai_service_contracts.schema import (
    ContractValidationError,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)
from pydantic import ValidationError

_NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
_ACTION_ID = UUID(int=1)
_FINGERPRINT = "sha256:" + "a" * 64


def _proofs() -> tuple[SafeguardProof, ...]:
    return tuple(
        SafeguardProof(kind=kind, proof_digest="sha256:" + f"{index:x}" * 64)
        for index, kind in enumerate(SafeguardProofKind, start=1)
    )


def _bundle(
    *,
    proofs: tuple[SafeguardProof, ...] | None = None,
    recorded_at: datetime = _NOW,
) -> SafeguardProofBundle:
    return SafeguardProofBundle.create(
        action_id=_ACTION_ID,
        execution_path=ExecutionPath.DIRECT_API,
        execution_fingerprint=_FINGERPRINT,
        source_revision="commit:" + "b" * 40,
        recorded_at=recorded_at,
        proofs=proofs or _proofs(),
    )


def test_bundle_canonicalizes_all_seven_proofs_and_exports() -> None:
    offset = timezone(timedelta(hours=9))
    bundle = _bundle(proofs=tuple(reversed(_proofs())), recorded_at=_NOW.astimezone(offset))

    assert tuple(proof.kind for proof in bundle.proofs) == tuple(SafeguardProofKind)
    assert bundle.recorded_at == _NOW
    assert bundle.effect_verified is False
    assert bundle.execution_authority is False
    assert bundle.approval_authority is False
    assert bundle.promotion_authority is False
    assert len(bundle.bundle_digest) == 71
    assert ExportedSafeguardProofBundle is SafeguardProofBundle
    assert ExecutorSafeguardProofBundle is SafeguardProofBundle


def test_bundle_and_schema_reject_incomplete_or_noncanonical_proofs() -> None:
    with pytest.raises(ValidationError, match="at least 7 items"):
        _bundle(proofs=_proofs()[:-1])

    bundle = _bundle()
    reversed_payload = bundle.model_dump(mode="json")
    reversed_payload["proofs"] = list(reversed(reversed_payload["proofs"]))
    with pytest.raises(ValidationError, match="seven ordered proof classes"):
        SafeguardProofBundle.model_validate(reversed_payload)

    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    with pytest.raises(ContractValidationError, match="stop_condition"):
        validator.validate(
            "execution-safeguard-proof-bundle",
            reversed_payload,
            version="1.0.0",
        )


def test_bundle_rejects_duplicate_proofs_authority_and_digest_tampering() -> None:
    duplicate = (*_proofs()[:-1], _proofs()[0])
    with pytest.raises(ValidationError, match="seven ordered proof classes"):
        _bundle(proofs=duplicate)

    with pytest.raises(ValidationError, match="Input should be False"):
        SafeguardProofBundle.create(
            action_id=_ACTION_ID,
            execution_path=ExecutionPath.DIRECT_API,
            execution_fingerprint=_FINGERPRINT,
            source_revision="commit:" + "b" * 40,
            recorded_at=_NOW,
            proofs=_proofs(),
            execution_authority=True,
        )

    bundle = _bundle()
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    duplicate_payload = bundle.model_dump(mode="json")
    for proof in duplicate_payload["proofs"]:
        proof["proof_digest"] = "sha256:" + "1" * 64
    with pytest.raises(ContractValidationError, match="proof digests MUST be unique"):
        validator.validate("execution-safeguard-proof-bundle", duplicate_payload)

    tampered_payload = {
        **bundle.model_dump(mode="json"),
        "bundle_digest": "sha256:" + "0" * 64,
    }
    with pytest.raises(ValidationError, match="digest mismatched"):
        SafeguardProofBundle.model_validate(tampered_payload)
    with pytest.raises(ContractValidationError, match="digest mismatched"):
        validator.validate("execution-safeguard-proof-bundle", tampered_payload)


def test_schema_accepts_the_canonical_bundle_and_is_registered() -> None:
    registry = PackageResourceSchemaRegistry()
    validator = JsonSchemaContractValidator(registry)
    bundle = _bundle()

    validator.validate(
        "execution-safeguard-proof-bundle",
        bundle.model_dump(mode="json"),
        version=bundle.schema_version,
    )

    assert "execution-safeguard-proof-bundle" in registry.names()
    schema_id = registry.get("execution-safeguard-proof-bundle", "1.0.0")["$id"]
    assert isinstance(schema_id, str)
    assert schema_id.endswith("/execution-safeguard-proof-bundle/1.0.0")
