"""Authority-neutral runtime binding decisions for the selected product profile."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fdai_service_contracts.product_profile import ProductAddOn, ProductProfile

from fdai.core.risk_gate import ActionPromotionRegistry


@dataclass(frozen=True, slots=True)
class RuntimeProductSelection:
    """Construction eligibility only; this record never grants runtime authority."""

    governed_execution: bool
    notifications: bool
    enterprise_identity: bool

    @classmethod
    def from_profile(cls, profile: ProductProfile) -> RuntimeProductSelection:
        return cls(
            governed_execution=profile.selects(ProductAddOn.GOVERNED_EXECUTION),
            notifications=profile.selects(ProductAddOn.NOTIFICATIONS),
            enterprise_identity=profile.selects(ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE),
        )


def build_promotion_registry(
    selection: RuntimeProductSelection,
    *,
    container: Any,
    audit_store: Any,
    durable: bool,
) -> tuple[ActionPromotionRegistry, Any | None]:
    """Bind durable enforcement only for the explicit governed-execution add-on."""

    if selection.governed_execution and durable:
        from fdai.delivery.persistence import (
            StateStoreActionPromotionRegistry,
            StateStoreOperatorOverrideAuthorityVerifier,
        )

        registry = StateStoreActionPromotionRegistry(
            store=audit_store,
            receipt_verifier=container.operational_promotion_receipt_verifier,
            persisted_authority_verifier=container.persisted_promotion_authority_verifier,
            override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(audit_store),
        )
        return registry, registry.refresh
    return (
        ActionPromotionRegistry(
            receipt_verifier=(
                container.operational_promotion_receipt_verifier
                if selection.governed_execution
                else None
            ),
            enforcement_enabled=selection.governed_execution,
        ),
        None,
    )


def build_stewardship_identity_health(
    selection: RuntimeProductSelection,
    *,
    store: Any,
    http_client: httpx.AsyncClient | None,
    identity: Any,
    environment: Mapping[str, str],
    config_path: Path,
) -> Any | None:
    if not selection.enterprise_identity:
        return None
    from fdai.runtime.stewardship_identity_health import (
        build_stewardship_identity_health_worker,
    )

    return build_stewardship_identity_health_worker(
        store=store,
        http_client=http_client,
        identity=identity,
        environment=environment,
        config_path=config_path,
    )


def build_hil_identity(
    selection: RuntimeProductSelection,
    *,
    environment: Mapping[str, str],
    resources: Any,
    identity_builder: Any,
) -> Any | None:
    """Construct the Teams approval identity only for both selected add-ons."""

    if (
        not selection.governed_execution
        or not selection.notifications
        or not environment.get("FDAI_TEAMS_APPROVAL_ACTIVITY_URL", "").strip()
    ):
        return None
    if resources.http_client is None:
        raise RuntimeError("Teams approval Bot delivery requires an HTTP client")
    return identity_builder(
        resources.http_client,
        client_id_env="FDAI_TEAMS_BOT_MI_CLIENT_ID",
        require_client_id=True,
    )


def build_effect_reconciliation_binding(
    selection: RuntimeProductSelection,
    **kwargs: Any,
) -> Any | None:
    if not selection.governed_execution:
        return None
    from fdai.runtime.bootstrap_bindings import build_effect_reconciliation_request_binding

    return build_effect_reconciliation_request_binding(**kwargs)


def build_vertical_execution_identities(
    selection: RuntimeProductSelection,
    *,
    http_client: httpx.AsyncClient | None,
) -> Mapping[str, Any]:
    if not selection.governed_execution:
        return {}
    from fdai.runtime.bootstrap_bindings import build_vertical_execution_identities

    return build_vertical_execution_identities(http_client=http_client)


__all__ = [
    "RuntimeProductSelection",
    "build_effect_reconciliation_binding",
    "build_hil_identity",
    "build_promotion_registry",
    "build_stewardship_identity_health",
    "build_vertical_execution_identities",
]
