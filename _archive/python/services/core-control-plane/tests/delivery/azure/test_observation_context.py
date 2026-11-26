"""Azure observation-context signing tests."""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import timedelta

import pytest
from fdai.delivery.azure.observation_context import (
    AzureObservationContextIdentity,
    build_azure_observation_context_pair,
)
from fdai.delivery.reconciliation import IndependentObservationContextVerifier

from tests.core.ontology_platform.test_reconciliation import _fixture, _request

_SEED = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode("ascii")


def _identity() -> AzureObservationContextIdentity:
    return AzureObservationContextIdentity(
        observer_credential_lineage="azure-managed-identity:observer",
        executor_credential_lineage="azure-managed-identity:executor",
        source_credential_lineage="azure-managed-identity:inventory",
        verifier_identity="observation-verifier:ohl-ed25519",
    )


def _evidence():
    release, target, plan, action_type = _fixture()
    return _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    ).evidence


async def test_issuer_and_authenticator_bind_exact_observation() -> None:
    evidence = _evidence()
    issuer, authenticator = build_azure_observation_context_pair(
        private_key_seed=_SEED,
        identity=_identity(),
        clock=lambda: evidence.recorded_at + timedelta(seconds=1),
    )

    context = await issuer.issue(evidence=evidence)
    verified = await IndependentObservationContextVerifier(authenticator=authenticator).verify(
        evidence=evidence,
        claimed_context=context,
    )

    assert verified == context
    assert context.verification_receipt.signature.startswith("base64:")
    assert context.verification_receipt.verifier_credential_lineage.startswith("ed25519:sha256:")


async def test_authenticator_rejects_tampered_signature() -> None:
    evidence = _evidence()
    issuer, authenticator = build_azure_observation_context_pair(
        private_key_seed=_SEED,
        identity=_identity(),
        clock=lambda: evidence.recorded_at,
    )
    context = await issuer.issue(evidence=evidence)
    signature = context.verification_receipt.signature
    encoded = signature.removeprefix("base64:")
    decoded = bytearray(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    decoded[0] ^= 1
    tampered_receipt = context.verification_receipt.model_copy(
        update={
            "signature": (
                "base64:" + base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
            )
        }
    )
    tampered = context.model_copy(update={"verification_receipt": tampered_receipt})

    with pytest.raises(ValueError, match="signature is invalid"):
        await authenticator.authenticate(evidence=evidence, claimed_context=tampered)


async def test_authenticator_rejects_substituted_identity() -> None:
    evidence = _evidence()
    issuer, authenticator = build_azure_observation_context_pair(
        private_key_seed=_SEED,
        identity=_identity(),
        clock=lambda: evidence.recorded_at,
    )
    context = await issuer.issue(evidence=evidence)
    substituted = context.model_copy(update={"source_identity": "substituted-source"})

    with pytest.raises(ValueError, match="signature is invalid"):
        await authenticator.authenticate(evidence=evidence, claimed_context=substituted)


def test_signing_seed_must_be_canonical_32_byte_base64url() -> None:
    with pytest.raises(ValueError, match="unpadded base64url"):
        build_azure_observation_context_pair(
            private_key_seed=base64.urlsafe_b64encode(b"short").rstrip(b"=").decode("ascii"),
            identity=_identity(),
        )
    with pytest.raises(ValueError, match="unpadded base64url"):
        build_azure_observation_context_pair(
            private_key_seed=_SEED + "=",
            identity=_identity(),
        )


async def test_issuer_rejects_late_verification() -> None:
    evidence = _evidence()
    issuer, _ = build_azure_observation_context_pair(
        private_key_seed=_SEED,
        identity=_identity(),
        clock=lambda: evidence.recorded_at + timedelta(minutes=2),
    )

    with pytest.raises(ValueError, match="outside the issue window"):
        await issuer.issue(evidence=evidence)


def test_identity_rejects_collapsed_credential_lineage() -> None:
    with pytest.raises(ValueError, match="credential lineages MUST be distinct"):
        replace(
            _identity(),
            executor_credential_lineage="azure-managed-identity:observer",
        )
