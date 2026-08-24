"""Authenticate typed runtime-call telemetry before ontology projection."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from .runtime_call_projection import RuntimeCallObservation

_MAX_TEXT_LENGTH = 512


def _bounded_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_TEXT_LENGTH:
        raise ValueError(f"runtime call {field_name} MUST be bounded non-empty text")
    return normalized


def _timestamp(value: datetime, *, field_name: str) -> str:
    if value.tzinfo is None:
        raise ValueError(f"runtime call {field_name} MUST be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(body: object) -> str:
    encoded = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeCallTelemetryEnvelope:
    """Untrusted typed telemetry carrying exact candidate Resource identities."""

    observation_id: str
    caller_resource_ids: tuple[str, ...]
    target_resource_ids: tuple[str, ...]
    scope_ref: str
    observed_at: datetime
    evidence_cutoff: datetime
    recorded_at: datetime
    freshness_ceiling_seconds: int
    source_identity: str
    source_revision: str
    evidence_ref: str
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False

    def __post_init__(self) -> None:
        self.to_observation(authentication_ref="sha256:" + "0" * 64)

    def content_digest(self) -> str:
        """Return the replay-stable digest authenticated by the source verifier."""

        return _digest(
            {
                "caller_resource_ids": self.caller_resource_ids,
                "evidence_cutoff": _timestamp(
                    self.evidence_cutoff,
                    field_name="evidence_cutoff",
                ),
                "evidence_ref": self.evidence_ref,
                "execution_authority": self.execution_authority,
                "freshness_ceiling_seconds": self.freshness_ceiling_seconds,
                "mutation_authority": self.mutation_authority,
                "observation_id": self.observation_id,
                "observed_at": _timestamp(self.observed_at, field_name="observed_at"),
                "recorded_at": _timestamp(self.recorded_at, field_name="recorded_at"),
                "scope_ref": self.scope_ref,
                "source_identity": self.source_identity,
                "source_revision": self.source_revision,
                "target_resource_ids": self.target_resource_ids,
            }
        )

    def to_observation(self, *, authentication_ref: str) -> RuntimeCallObservation:
        """Create the projection input after authentication succeeds."""

        return RuntimeCallObservation(
            observation_id=self.observation_id,
            caller_resource_ids=self.caller_resource_ids,
            target_resource_ids=self.target_resource_ids,
            scope_ref=self.scope_ref,
            observed_at=self.observed_at,
            evidence_cutoff=self.evidence_cutoff,
            recorded_at=self.recorded_at,
            freshness_ceiling_seconds=self.freshness_ceiling_seconds,
            source_identity=self.source_identity,
            source_revision=self.source_revision,
            evidence_ref=self.evidence_ref,
            authentication_ref=authentication_ref,
            execution_authority=self.execution_authority,
            mutation_authority=self.mutation_authority,
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedRuntimeCallContext:
    """Trusted authentication result supplied separately from telemetry."""

    observation_id: str
    observation_digest: str
    source_identity: str
    source_credential_lineage: str
    verifier_identity: str
    verifier_credential_lineage: str
    authentication_ref: str
    verified_at: datetime
    signature_verified: Literal[True]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("observation_id", self.observation_id),
            ("observation_digest", self.observation_digest),
            ("source_identity", self.source_identity),
            ("source_credential_lineage", self.source_credential_lineage),
            ("verifier_identity", self.verifier_identity),
            ("verifier_credential_lineage", self.verifier_credential_lineage),
            ("authentication_ref", self.authentication_ref),
        ):
            _bounded_text(value, field_name=field_name)
        _timestamp(self.verified_at, field_name="verified_at")
        for field_name, value in (
            ("observation_digest", self.observation_digest),
            ("authentication_ref", self.authentication_ref),
        ):
            if not _is_digest(value):
                raise ValueError(f"runtime call {field_name} MUST be canonical SHA-256")
        if not self.signature_verified:
            raise ValueError("runtime call authentication signature MUST be verified")


class RuntimeCallTelemetryAuthenticator(Protocol):
    """Authenticate one runtime-call envelope without granting action authority."""

    async def authenticate(
        self,
        *,
        envelope: RuntimeCallTelemetryEnvelope,
        claimed_context: AuthenticatedRuntimeCallContext,
    ) -> AuthenticatedRuntimeCallContext: ...


class RuntimeCallTelemetryProducer:
    """Produce projection input only from exact independently authenticated telemetry."""

    def __init__(
        self,
        *,
        authenticator: RuntimeCallTelemetryAuthenticator,
        timeout_seconds: float = 2.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("runtime call authentication timeout MUST be positive")
        self._authenticator = authenticator
        self._timeout_seconds = timeout_seconds

    async def produce(
        self,
        *,
        envelope: RuntimeCallTelemetryEnvelope,
        claimed_context: AuthenticatedRuntimeCallContext,
    ) -> RuntimeCallObservation:
        """Return one typed observation or reject mismatched authentication evidence."""

        async with asyncio.timeout(self._timeout_seconds):
            authenticated = await self._authenticator.authenticate(
                envelope=envelope,
                claimed_context=claimed_context,
            )
        if authenticated != claimed_context:
            raise ValueError("authenticated runtime call context differs from claimed context")
        if authenticated.observation_id != envelope.observation_id:
            raise ValueError("runtime call authentication does not bind the observation identity")
        if authenticated.observation_digest != envelope.content_digest():
            raise ValueError("runtime call authentication does not bind exact telemetry")
        if authenticated.source_identity != envelope.source_identity:
            raise ValueError("runtime call authentication source does not match telemetry")
        if authenticated.verified_at < envelope.recorded_at:
            raise ValueError("runtime call authentication MUST NOT precede recorded telemetry")
        _require_distinct(
            "runtime call identities",
            authenticated.source_identity,
            authenticated.verifier_identity,
        )
        _require_distinct(
            "runtime call credential lineages",
            authenticated.source_credential_lineage,
            authenticated.verifier_credential_lineage,
        )
        return envelope.to_observation(authentication_ref=authenticated.authentication_ref)


def _require_distinct(label: str, *values: str) -> None:
    normalized = {value.strip().casefold() for value in values}
    if len(normalized) != len(values):
        raise ValueError(f"{label} MUST be distinct")


def _is_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


__all__ = [
    "AuthenticatedRuntimeCallContext",
    "RuntimeCallTelemetryAuthenticator",
    "RuntimeCallTelemetryEnvelope",
    "RuntimeCallTelemetryProducer",
]
