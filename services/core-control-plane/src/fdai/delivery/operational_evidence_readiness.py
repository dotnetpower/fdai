"""Settings projection rows for operational evidence issuance, one row per purpose.

Each row separates availability, deployment preference, and authority. A purpose is
``available`` only when the pinned registries load, the purpose has no registry or anchor
defect, a source readback is bound for it, and an observed verifier readiness snapshot shows a
writer-exclusive proof store. Availability grants no authority: every row reports shadow
authority and no execution or promotion authority. Configuration values are never echoed.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from fdai_service_contracts.operational_evidence import OPERATIONAL_EVIDENCE_PURPOSES

from fdai.core.operational_evidence.registry_json import RegistryUnavailableError
from fdai.core.operational_evidence.trust_registry import purpose_defects
from fdai.delivery.operational_evidence_configuration import (
    VERIFIER_ID,
    OperationalEvidenceSettings,
    load_anchors,
    load_registry_history,
)
from fdai.delivery.repo_assets import repo_asset_root

BOUND_READBACK_PURPOSES = frozenset(
    {"operational-test-context", "operator-test-context-command", "test-context-transition"}
)
_SOURCE_LIMITATIONS = {
    "case-history-read": "no retained Operator authentication receipt per semantic request exists",
    "current-case-reuse": "current safety results are not retained as readable receipts",
    "forecast-context": "the four forecast-history slices cannot be issued yet",
    "operational-test-observation": "no verifier-identity metric or health readback is bound",
}
_FORECAST_LIMITATION = "raw forecast history sources are not attestable yet (#1021)"


def operational_evidence_projection(
    env: Mapping[str, str],
    *,
    verifier_readiness: Mapping[str, object] | None = None,
    root: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Return one row per purpose; ``verifier_readiness`` comes from the verifier endpoint."""

    settings = OperationalEvidenceSettings.from_environment(env)
    prerequisites = settings.prerequisites()
    configured = settings.enabled or any(prerequisites.values())
    registry_reason: str | None = None
    defects: dict[str, tuple[str, ...]] = {}
    at = now or datetime.now(UTC)
    if all(prerequisites.values()):
        try:
            history = load_registry_history(settings, root=root or repo_asset_root())
            anchors = load_anchors(settings)
        except (OSError, RegistryUnavailableError, ValueError):
            registry_reason = "a pinned registry or the anchor binding is unavailable"
        else:
            defects = {
                purpose: purpose_defects(
                    history.current.trust,
                    anchors,
                    purpose_id=purpose,
                    verifier_id=VERIFIER_ID,
                    at=at,
                )
                for purpose in OPERATIONAL_EVIDENCE_PURPOSES
            }
    else:
        registry_reason = "deployment prerequisites are incomplete"
    state = str((verifier_readiness or {}).get("state", "unobserved"))
    raw_bound = (verifier_readiness or {}).get("bound_purposes", ())
    bound = frozenset(
        str(item) for item in (raw_bound if isinstance(raw_bound, (list, tuple)) else ())
    )
    return [
        _row(
            purpose,
            settings=settings,
            prerequisites=prerequisites,
            configured=configured,
            registry_reason=registry_reason,
            defects=defects.get(purpose, ()),
            verifier_state=state,
            verifier_bound=purpose in bound,
        )
        for purpose in OPERATIONAL_EVIDENCE_PURPOSES
    ]


def _row(
    purpose: str,
    *,
    settings: OperationalEvidenceSettings,
    prerequisites: Mapping[str, bool],
    configured: bool,
    registry_reason: str | None,
    defects: tuple[str, ...],
    verifier_state: str,
    verifier_bound: bool,
) -> dict[str, object]:
    readback_bound = purpose in BOUND_READBACK_PURPOSES
    self_verified = "self_verified" in defects or verifier_state == "self_verified"
    reason: str | None
    if not settings.enabled:
        reason = "not enabled by deployment configuration"
    elif registry_reason is not None:
        reason = registry_reason
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
    elif verifier_state != "ready" or not verifier_bound:
        reason = "verifier readiness with a writer-exclusive proof store is not observed"
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
            {"name": "pinned_registries_and_anchors", "satisfied": registry_reason is None},
            {
                "name": "purpose_registry_entry",
                "satisfied": registry_reason is None and not defects,
            },
            {"name": "source_readback_bound", "satisfied": readback_bound},
            {"name": "writer_exclusive_proof_store", "satisfied": verifier_state == "ready"},
        ],
    }


__all__ = ["BOUND_READBACK_PURPOSES", "operational_evidence_projection"]
