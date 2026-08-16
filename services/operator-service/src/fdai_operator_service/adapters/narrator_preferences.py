"""Revisioned per-principal narrator preference and its sanitized Settings projection.

One authenticated principal may keep `Auto` narrator routing or pin exactly one
deployment from the current narrator allowlist. The preference applies only to
the T1 narrator: T1 internal judgment, embeddings, and every T2 secondary,
critic, rubric, and escalation binding stay system-governed and are never
personalized here.

Writes are revisioned. Creation sends revision `0` and a later write MUST match
the stored revision, so a concurrent session receives a conflict instead of
silently overwriting another session's choice. Reads are principal-scoped: one
principal can neither observe nor overwrite another principal's preference.

The projection is sanitized. It exposes deployment names, revision, routing
mode, and rolling timing evidence, and never exposes endpoints, URLs, audiences,
tokens, or credentials.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from fdai_operator_service.adapters.narrator_latency import NarratorLatencyStats

AUTO_DEPLOYMENT = "auto"
_MAX_PRINCIPAL_CHARS = 128
_MAX_DEPLOYMENT_CHARS = 64
_APPLIES_TO = "t1_narrator"


class NarratorPreferenceError(ValueError):
    """One preference write violated the server-owned preference contract."""


class NarratorPreferenceConflictError(NarratorPreferenceError):
    """The submitted revision does not match the stored revision."""


@dataclass(frozen=True, slots=True)
class NarratorPreference:
    """One principal's stored narrator routing choice."""

    principal_id: str
    deployment: str
    revision: int

    @property
    def is_auto(self) -> bool:
        return self.deployment == AUTO_DEPLOYMENT


@dataclass(slots=True)
class InMemoryNarratorPreferenceStore:
    """Process-local revisioned preference store for the independent service.

    The store keeps no endpoint, credential, or model-binding state. A deployment
    that leaves the allowlist is not rewritten on read; the projection degrades to
    `Auto` so a later allowlist restoration keeps the operator's original choice.
    """

    _preferences: dict[str, NarratorPreference]

    def __init__(self) -> None:
        self._preferences = {}

    def read(self, principal_id: str) -> NarratorPreference:
        principal = _principal(principal_id)
        stored = self._preferences.get(principal)
        if stored is None:
            return NarratorPreference(
                principal_id=principal,
                deployment=AUTO_DEPLOYMENT,
                revision=0,
            )
        return stored

    def write(
        self,
        principal_id: str,
        *,
        deployment: str,
        expected_revision: int,
        allowlist: Iterable[str],
    ) -> NarratorPreference:
        principal = _principal(principal_id)
        selected = _deployment(deployment)
        allowed = _allowlist(allowlist)
        if selected != AUTO_DEPLOYMENT and selected not in allowed:
            raise NarratorPreferenceError("narrator preference MUST name an allowlisted deployment")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            raise NarratorPreferenceError("narrator preference revision MUST be an integer")
        current = self.read(principal)
        if expected_revision != current.revision:
            raise NarratorPreferenceConflictError("narrator preference revision conflict")
        updated = NarratorPreference(
            principal_id=principal,
            deployment=selected,
            revision=current.revision + 1,
        )
        self._preferences[principal] = updated
        return updated


def project_narrator_settings(
    *,
    principal_id: str,
    preference: NarratorPreference,
    allowlist: Sequence[str],
    latency: Sequence[NarratorLatencyStats] = (),
) -> Mapping[str, object]:
    """Return the sanitized Settings projection for one principal.

    A stored deployment that is no longer allowlisted degrades to `Auto` with an
    explicit reason instead of routing to an unavailable candidate.
    """

    principal = _principal(principal_id)
    if preference.principal_id != principal:
        raise NarratorPreferenceError("narrator preference belongs to another principal")
    allowed = _allowlist(allowlist)
    effective = preference.deployment
    fallback_reason: str | None = None
    if not preference.is_auto and preference.deployment not in allowed:
        effective = AUTO_DEPLOYMENT
        fallback_reason = "deployment_unavailable"
    return {
        "applies_to": _APPLIES_TO,
        "personalizes_t2_bindings": False,
        "mode": "auto" if effective == AUTO_DEPLOYMENT else "pinned",
        "selected_deployment": None if effective == AUTO_DEPLOYMENT else effective,
        "stored_deployment": preference.deployment,
        "fallback_reason": fallback_reason,
        "revision": preference.revision,
        "available_deployments": sorted(allowed),
        "latency": [
            {
                "deployment": stats.deployment,
                "sample_count": stats.sample_count,
                "latency_p50_ms": stats.latency_p50_ms,
                "latency_p95_ms": stats.latency_p95_ms,
                "ttft_p50_ms": stats.ttft_p50_ms,
                "ttft_p95_ms": stats.ttft_p95_ms,
            }
            for stats in latency
            if stats.deployment in allowed
        ],
    }


def _principal(value: str) -> str:
    if not isinstance(value, str):
        raise NarratorPreferenceError("narrator preference principal MUST be a string")
    principal = value.strip()
    if not principal or len(principal) > _MAX_PRINCIPAL_CHARS:
        raise NarratorPreferenceError(
            f"narrator preference principal MUST be 1-{_MAX_PRINCIPAL_CHARS} characters"
        )
    return principal


def _deployment(value: str) -> str:
    if not isinstance(value, str):
        raise NarratorPreferenceError("narrator preference deployment MUST be a string")
    deployment = value.strip()
    if not deployment or len(deployment) > _MAX_DEPLOYMENT_CHARS:
        raise NarratorPreferenceError(
            f"narrator preference deployment MUST be 1-{_MAX_DEPLOYMENT_CHARS} characters"
        )
    return deployment


def _allowlist(values: Iterable[str]) -> frozenset[str]:
    allowed = frozenset(_deployment(value) for value in values)
    if AUTO_DEPLOYMENT in allowed:
        raise NarratorPreferenceError("narrator allowlist MUST NOT contain the auto sentinel")
    return allowed


__all__ = [
    "AUTO_DEPLOYMENT",
    "InMemoryNarratorPreferenceStore",
    "NarratorPreference",
    "NarratorPreferenceConflictError",
    "NarratorPreferenceError",
    "project_narrator_settings",
]
