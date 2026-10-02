"""Settings projection rows for operational evidence issuance, one row per purpose.

Each row separates availability, deployment preference, and authority. A purpose is
``available`` only when the pinned registries load without a defect for it, a source readback
is bound for it, and a current verifier readiness snapshot names the same registry pins, an
active binding of its own verifier version, a writer-exclusive proof store, the purpose among
its bound purposes, and every source the purpose declares as healthy. Configuration alone never
proves availability, and availability grants no authority: every row reports shadow authority
and no execution or promotion authority. Configuration values are never echoed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fdai_service_contracts.operational_evidence import (
    OPERATIONAL_EVIDENCE_PURPOSES,
    OperationalEvidenceSourceHealth,
    OperationalEvidenceVerifierReadiness,
    OperationalEvidenceVerifierState,
)
from pydantic import ValidationError

from fdai.core.operational_evidence.registry_json import RegistryUnavailableError
from fdai.core.operational_evidence.revision_history import RegistryHistory
from fdai.core.operational_evidence.trust_registry import (
    DeploymentAnchors,
    PurposeTrust,
    purpose_defects,
)
from fdai.delivery.operational_evidence_configuration import (
    VERIFIER_ID,
    OperationalEvidenceSettings,
    load_anchors,
    load_registry_history,
)
from fdai.delivery.operational_evidence_transport import read_verifier_readiness
from fdai.delivery.repo_assets import repo_asset_root

BOUND_READBACK_PURPOSES = frozenset(
    {
        "case-history-read",
        "forecast-history-actions",
        "forecast-history-changes",
        "forecast-history-resource_lifecycle",
        "operational-test-context",
        "operator-test-context-command",
        "test-context-transition",
    }
)
READINESS_MAX_AGE = timedelta(seconds=120)
READINESS_MAX_SKEW = timedelta(seconds=30)
_SOURCE_LIMITATIONS = {
    "forecast-history-excluded_windows": (
        "no revisioned ChangeWindow history producer exists; current sources only expose "
        "OntologyChangeWindowEvidenceProvider.is_active, OperatingIntentAdmission, and "
        "OntologyInstanceStore current graph revisions"
    ),
    "current-case-reuse": "verifier-identity current-case provider readback is unavailable",
    "forecast-context": (
        "all four source-specific forecast-history admissions are required; "
        "forecast-history-excluded_windows remains unavailable"
    ),
    "operational-test-observation": "verifier-identity provider readback is unavailable",
}
_FORECAST_LIMITATION = (
    "source-specific forecast readback is bound for actions, changes, and resource_lifecycle; "
    "excluded_windows remains unavailable"
)
_WRITER_NOT_READY = "verifier readiness with a writer-exclusive proof store is not observed"
_READY = OperationalEvidenceVerifierState.READY
_HEALTHY = OperationalEvidenceSourceHealth.HEALTHY


@dataclass(frozen=True, slots=True)
class _Registries:
    """The Core's own pinned registries and anchors, or why they cannot be loaded."""

    history: RegistryHistory | None
    anchors: DeploymentAnchors | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class _Observation:
    """One parsed readiness snapshot and why it cannot vouch for any purpose, if it cannot."""

    readiness: OperationalEvidenceVerifierReadiness | None
    reason: str | None

    @property
    def self_verified(self) -> bool:
        return (
            self.readiness is not None
            and self.readiness.state is OperationalEvidenceVerifierState.SELF_VERIFIED
        )

    @property
    def writer_exclusive(self) -> bool:
        return self.reason is None and self.readiness is not None and self.readiness.state is _READY


async def observe_verifier_readiness(
    env: Mapping[str, str], *, client: httpx.AsyncClient | None = None
) -> OperationalEvidenceVerifierReadiness | None:
    """Read the verifier readiness endpoint once when issuance is enabled and bound.

    Nothing is read while issuance is disabled or the endpoint is unset, and any failure
    leaves the verifier unobserved, which keeps every purpose unavailable.
    """

    settings = OperationalEvidenceSettings.from_environment(env)
    if not settings.enabled or not settings.verifier_url:
        return None
    if client is not None:
        return await read_verifier_readiness(client, base_url=settings.verifier_url)
    async with httpx.AsyncClient(timeout=2.0) as owned:
        return await read_verifier_readiness(owned, base_url=settings.verifier_url)


def operational_evidence_projection(
    env: Mapping[str, str],
    *,
    verifier_readiness: OperationalEvidenceVerifierReadiness | Mapping[str, object] | None = None,
    root: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Return one row per purpose; ``verifier_readiness`` comes from the verifier endpoint."""

    settings = OperationalEvidenceSettings.from_environment(env)
    prerequisites = settings.prerequisites()
    configured = settings.enabled or any(prerequisites.values())
    at = now or datetime.now(UTC)
    registries = _registries(settings, prerequisites, root=root)
    defects: dict[str, tuple[str, ...]] = {}
    if registries.history is not None and registries.anchors is not None:
        defects = {
            purpose: purpose_defects(
                registries.history.current.trust,
                registries.anchors,
                purpose_id=purpose,
                verifier_id=VERIFIER_ID,
                at=at,
            )
            for purpose in OPERATIONAL_EVIDENCE_PURPOSES
        }
    observation = _observe(verifier_readiness, registries.history, at)
    return [
        _row(
            purpose,
            settings=settings,
            prerequisites=prerequisites,
            configured=configured,
            registries=registries,
            defects=defects.get(purpose, ()),
            observation=observation,
            at=at,
        )
        for purpose in OPERATIONAL_EVIDENCE_PURPOSES
    ]


def _registries(
    settings: OperationalEvidenceSettings, prerequisites: Mapping[str, bool], *, root: Path | None
) -> _Registries:
    if not all(prerequisites.values()):
        return _Registries(None, None, "deployment prerequisites are incomplete")
    try:
        history = load_registry_history(settings, root=root or repo_asset_root())
        anchors = load_anchors(settings)
    except (OSError, RegistryUnavailableError, ValueError):
        return _Registries(None, None, "a pinned registry or the anchor binding is unavailable")
    return _Registries(history, anchors, None)


def _observe(
    raw: OperationalEvidenceVerifierReadiness | Mapping[str, object] | None,
    history: RegistryHistory | None,
    at: datetime,
) -> _Observation:
    if raw is None:
        return _Observation(None, "verifier readiness is not observed")
    try:
        readiness = (
            raw
            if isinstance(raw, OperationalEvidenceVerifierReadiness)
            else OperationalEvidenceVerifierReadiness.model_validate(raw)
        )
    except (ValidationError, ValueError):
        return _Observation(None, "verifier readiness is malformed")
    if readiness.verifier_id != VERIFIER_ID:
        return _Observation(readiness, "verifier readiness names another verifier identity")
    if history is not None and (
        readiness.trust_registry_pin != history.current.pins.trust_pin
        or readiness.grant_registry_pin != history.current.pins.grant_pin
    ):
        return _Observation(readiness, "verifier registry pins differ from the pinned registries")
    probed = readiness.probed_at
    if probed is None or at - probed > READINESS_MAX_AGE or probed - at > READINESS_MAX_SKEW:
        return _Observation(readiness, "verifier readiness is not current")
    return _Observation(readiness, None)


def _binding_active(
    registries: _Registries,
    readiness: OperationalEvidenceVerifierReadiness,
    purpose: str,
    at: datetime,
) -> bool:
    if registries.history is None or registries.anchors is None:
        return False
    return not purpose_defects(
        registries.history.current.trust,
        registries.anchors,
        purpose_id=purpose,
        verifier_id=VERIFIER_ID,
        verifier_version=readiness.verifier_version,
        at=at,
    )


def _unhealthy_sources(
    entry: PurposeTrust | None, readiness: OperationalEvidenceVerifierReadiness
) -> tuple[str, ...]:
    if entry is None:
        return ("purpose_not_registered",)
    return tuple(
        sorted(
            source.source_id
            for source in entry.sources
            if readiness.source_health.get(source.source_id) is not _HEALTHY
        )
    )


def _row(
    purpose: str,
    *,
    settings: OperationalEvidenceSettings,
    prerequisites: Mapping[str, bool],
    configured: bool,
    registries: _Registries,
    defects: tuple[str, ...],
    observation: _Observation,
    at: datetime,
) -> dict[str, object]:
    readback_bound = purpose in BOUND_READBACK_PURPOSES
    self_verified = "self_verified" in defects or observation.self_verified
    readiness = observation.readiness if observation.reason is None else None
    purpose_bound = readiness is not None and purpose in readiness.bound_purposes
    binding_active = readiness is not None and _binding_active(registries, readiness, purpose, at)
    entry = (
        registries.history.current.trust.purpose(purpose)
        if registries.history is not None
        else None
    )
    unhealthy = _unhealthy_sources(entry, readiness) if readiness is not None else ("unobserved",)
    reason: str | None
    if not settings.enabled:
        reason = "not enabled by deployment configuration"
    elif registries.reason is not None:
        reason = registries.reason
    elif self_verified:
        reason = "self_verified: another principal can write or share the verifier identity"
    elif defects:
        reason = "the pinned registry entry or its anchors are unavailable"
    elif not readback_bound:
        reason = (
            _FORECAST_LIMITATION
            if purpose.startswith("forecast-history-")
            else _SOURCE_LIMITATIONS.get(purpose, "no source readback is bound")
        )
    elif observation.reason is not None:
        reason = observation.reason
    elif not observation.writer_exclusive:
        reason = _WRITER_NOT_READY
    elif not purpose_bound:
        reason = "the verifier has not bound a source readback for this purpose"
    elif not binding_active:
        reason = "the observed verifier version has no active binding for this purpose"
    elif unhealthy:
        reason = "declared sources are not healthy: " + ", ".join(unhealthy)
    else:
        reason = None
    available = reason is None
    return {
        "key": f"operational-evidence.{purpose}",
        "source": "core-control-plane",
        "observed": True,
        "configured": configured,
        "ready": available,
        "mode": "shadow" if settings.enabled else "disabled",
        "reason": reason,
        "available": available,
        "enabled": settings.enabled,
        "enabled_source": "deployment_configuration",
        "authority_mode": "shadow",
        "capability_state": (
            "available" if available else "self_verified" if self_verified else "unavailable"
        ),
        "execution_authority": False,
        "promotion_authority": False,
        "unavailable_reason": reason,
        "prerequisites": [
            *({"name": name, "satisfied": value} for name, value in sorted(prerequisites.items())),
            {"name": "pinned_registries_and_anchors", "satisfied": registries.reason is None},
            {
                "name": "purpose_registry_entry",
                "satisfied": registries.reason is None and not defects,
            },
            {"name": "source_readback_bound", "satisfied": readback_bound},
            {"name": "verifier_readiness_current", "satisfied": observation.reason is None},
            {"name": "writer_exclusive_proof_store", "satisfied": observation.writer_exclusive},
            {"name": "verifier_bound_purpose", "satisfied": purpose_bound},
            {"name": "verifier_binding_active", "satisfied": binding_active},
            {
                "name": "declared_sources_healthy",
                "satisfied": readiness is not None and not unhealthy,
            },
        ],
    }


__all__ = [
    "BOUND_READBACK_PURPOSES",
    "READINESS_MAX_AGE",
    "READINESS_MAX_SKEW",
    "observe_verifier_readiness",
    "operational_evidence_projection",
]
