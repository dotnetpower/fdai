"""Authenticated typed runtime-call telemetry producer tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.runtime_call_telemetry import (
    AuthenticatedRuntimeCallContext,
    RuntimeCallTelemetryEnvelope,
    RuntimeCallTelemetryProducer,
)

NOW = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)


def _envelope() -> RuntimeCallTelemetryEnvelope:
    return RuntimeCallTelemetryEnvelope(
        observation_id="runtime-call:one",
        caller_resource_ids=("resource:caller",),
        target_resource_ids=("resource:target",),
        scope_ref="scope:operations-review",
        observed_at=NOW - timedelta(minutes=2),
        evidence_cutoff=NOW - timedelta(minutes=1),
        recorded_at=NOW,
        freshness_ceiling_seconds=300,
        source_identity="telemetry.runtime-calls",
        source_revision="1.0.0",
        evidence_ref="telemetry:runtime-call:one",
    )


def _context(envelope: RuntimeCallTelemetryEnvelope) -> AuthenticatedRuntimeCallContext:
    return AuthenticatedRuntimeCallContext(
        observation_id=envelope.observation_id,
        observation_digest=envelope.content_digest(),
        source_identity=envelope.source_identity,
        source_credential_lineage="credential-lineage:telemetry",
        verifier_identity="runtime-call-authenticator",
        verifier_credential_lineage="credential-lineage:verifier",
        authentication_ref="sha256:" + "1" * 64,
        verified_at=NOW + timedelta(seconds=1),
        signature_verified=True,
    )


class _Authenticator:
    def __init__(self, result: AuthenticatedRuntimeCallContext) -> None:
        self._result = result

    async def authenticate(
        self,
        *,
        envelope: RuntimeCallTelemetryEnvelope,
        claimed_context: AuthenticatedRuntimeCallContext,
    ) -> AuthenticatedRuntimeCallContext:
        del envelope, claimed_context
        return self._result


async def test_authenticated_exact_telemetry_produces_typed_observation() -> None:
    envelope = _envelope()
    context = _context(envelope)

    observation = await RuntimeCallTelemetryProducer(authenticator=_Authenticator(context)).produce(
        envelope=envelope, claimed_context=context
    )

    assert observation.observation_id == envelope.observation_id
    assert observation.caller_resource_ids == ("resource:caller",)
    assert observation.target_resource_ids == ("resource:target",)
    assert observation.authentication_ref == context.authentication_ref
    assert observation.execution_authority is False
    assert observation.mutation_authority is False


@pytest.mark.parametrize(
    "tampered_context",
    [
        lambda context: replace(context, observation_id="runtime-call:other"),
        lambda context: replace(context, observation_digest="sha256:" + "2" * 64),
        lambda context: replace(context, source_identity="telemetry.other"),
    ],
)
async def test_mismatched_authentication_never_produces_observation(tampered_context) -> None:  # type: ignore[no-untyped-def]
    envelope = _envelope()
    claimed = _context(envelope)
    authenticated = tampered_context(claimed)

    with pytest.raises(ValueError):
        await RuntimeCallTelemetryProducer(authenticator=_Authenticator(authenticated)).produce(
            envelope=envelope, claimed_context=claimed
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"verifier_identity": "TELEMETRY.RUNTIME-CALLS"}, "identities MUST be distinct"),
        (
            {"verifier_credential_lineage": "CREDENTIAL-LINEAGE:TELEMETRY"},
            "credential lineages MUST be distinct",
        ),
    ],
)
async def test_source_cannot_authenticate_itself(
    changes: dict[str, object],
    message: str,
) -> None:
    envelope = _envelope()
    context = replace(_context(envelope), **changes)

    with pytest.raises(ValueError, match=message):
        await RuntimeCallTelemetryProducer(authenticator=_Authenticator(context)).produce(
            envelope=envelope, claimed_context=context
        )


def test_authentication_context_requires_canonical_digests() -> None:
    envelope = _envelope()

    with pytest.raises(ValueError, match="canonical SHA-256"):
        replace(_context(envelope), authentication_ref="receipt:not-content-addressed")
