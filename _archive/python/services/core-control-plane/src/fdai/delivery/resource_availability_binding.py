"""Bind read-only availability detection to the audited Runtime Settings revision."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType

from fdai_service_contracts.resource_availability_settings import (
    DEFAULT_RESOURCE_AVAILABILITY_SETTINGS as DEFAULT_RESOURCE_AVAILABILITY_SETTINGS,
)
from fdai_service_contracts.resource_availability_settings import (
    RESOURCE_AVAILABILITY_SETTING_KEY as RESOURCE_AVAILABILITY_SETTING_KEY,
)
from fdai_service_contracts.resource_availability_settings import (
    AvailabilityPlannedStopSettings as AvailabilityPlannedStopSettings,
)
from fdai_service_contracts.resource_availability_settings import (
    AvailabilityResourcePolicySettings as AvailabilityResourcePolicySettings,
)
from fdai_service_contracts.resource_availability_settings import (
    ResourceAvailabilitySettings as ResourceAvailabilitySettings,
)
from fdai_service_contracts.resource_availability_settings import (
    validate_resource_availability_setting as validate_resource_availability_setting,
)
from pydantic import ValidationError

from fdai.core.investigation.analyzer import ResourceAnalyzer
from fdai.core.investigation.contract import AnalyzerFinding
from fdai.core.investigation.resource_availability import ResourceAvailabilityAnalyzer
from fdai.core.investigation.resource_availability_evidence import (
    PlannedStopWindow,
    ResourceAvailabilityPolicy,
    ResourceOperationalState,
)
from fdai.delivery.analyzer_recovery import RecoveryAwareAnalyzer
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.delivery.azure.resource_availability import (
    AZURE_AVAILABILITY_RESOURCE_TYPES,
    azure_resource_operational_state,
)
from fdai.delivery.resource_availability_inventory import (
    AvailabilityInventoryReader,
    InventoryResourceAvailabilitySource,
    ResourceAvailabilityBinding,
)
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class ResourceAvailabilityAnalyzerBinding:
    analyzers: tuple[ResourceAnalyzer, ...]
    settings_revision: int
    available: bool
    enabled: bool
    unavailable_reason: str | None = None
    monitored_resources: int = 0


@dataclass(frozen=True, slots=True)
class _TargetDispatchAvailabilityAnalyzer:
    kind: str
    leaves: Mapping[str, ResourceAnalyzer]
    settings_revision: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "leaves", MappingProxyType(dict(self.leaves)))

    @property
    def resource_kind(self) -> str:
        return self.kind

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        analyzer = self.leaves.get(resource_ref)
        if analyzer is None:
            return ()
        findings = await analyzer.analyze(
            resource_ref=resource_ref,
            window_seconds=window_seconds,
        )
        return tuple(
            replace(
                finding,
                metadata={
                    **finding.metadata,
                    "settings_reference": f"runtime-settings:revision:{self.settings_revision}",
                    "settings_revision": str(self.settings_revision),
                },
            )
            for finding in findings
        )


def resource_availability_scope_ref(logical_resource_ref: str) -> str:
    """Name an exact logical-resource scope without disclosing its provider identity."""

    digest = hashlib.sha256(logical_resource_ref.encode("utf-8")).hexdigest()
    return f"resource-scope:{digest}"


async def build_resource_availability_analyzers(
    *,
    settings: RuntimeSettingsService,
    inventory: AvailabilityInventoryReader | None,
    inventory_generation: str | None,
    targets: Sequence[AnalyzerTarget],
    state_store: StateStore,
    wall_clock: Callable[[], datetime] | None = None,
) -> ResourceAvailabilityAnalyzerBinding:
    """Read real versioned Settings and bind only exact current inventory identities.

    Missing catalog registration is explicitly unavailable, not an alternate
    store or an environment-variable fallback. Both settings and inventory
    revisions are fenced before returning. The source checks generation again
    on each observation. One dispatcher per kind selects its exact logical
    resource leaf before querying or reading recovery context.
    """

    try:
        values, revision = await settings.effective_values_with_revision()
    except Exception:  # noqa: BLE001 - settings failures MUST remain unavailable
        return ResourceAvailabilityAnalyzerBinding(
            (),
            0,
            False,
            False,
            "runtime_settings_unavailable",
        )
    raw = values.get(RESOURCE_AVAILABILITY_SETTING_KEY)
    if raw is None:
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            False,
            "setting_catalog_unregistered",
        )
    try:
        config = ResourceAvailabilitySettings.model_validate(raw)
    except ValidationError:
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            False,
            "runtime_settings_invalid",
        )
    unavailable = (
        "durable_runtime_settings_unavailable"
        if settings.store is None or not settings.durable
        else "inventory_unavailable"
        if inventory is None or not inventory_generation
        else None
    )
    if unavailable is not None or not config.enabled:
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            unavailable is None,
            config.enabled,
            unavailable,
        )
    selected = tuple(target for target in targets if target.resource_type in config.resource_types)
    if any(
        target.resource_type is None or target.provider_query_ref is None for target in selected
    ) or len({target.resource_ref for target in selected}) != len(selected):
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            True,
            "target_identity_unavailable",
        )
    resource_ids = tuple(sorted(target.resource_ref for target in selected))
    if len(resource_ids) > 1000:
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            True,
            "target_limit",
        )
    if inventory is None:
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            True,
            "inventory_unavailable",
        )
    try:
        async with asyncio.timeout(10.0):
            generation, records = await inventory.read_active_resources(resource_ids=resource_ids)
    except PermissionError:
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            True,
            "inventory_authorization_denied",
        )
    except Exception:  # noqa: BLE001 - no provider details cross the binding result
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            True,
            "inventory_unavailable",
        )
    if generation != inventory_generation:
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            True,
            "inventory_generation_changed",
        )
    if set(records) != set(resource_ids):
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            True,
            "inventory_target_coverage_incomplete",
        )
    bindings: list[ResourceAvailabilityBinding] = []
    for target in selected:
        record = records[target.resource_ref]
        declared = config.resources.get(target.resource_ref)
        if (
            record.resource_id != target.resource_ref
            or record.type != target.resource_type
            or record.provider_ref is None
            or target.provider_query_ref is None
            or record.provider_ref.casefold() != target.provider_query_ref.casefold()
            or (declared is not None and declared.resource_type != record.type)
        ):
            return ResourceAvailabilityAnalyzerBinding(
                (),
                revision,
                False,
                True,
                "inventory_target_identity_mismatch",
            )
        bindings.append(
            ResourceAvailabilityBinding(
                target.resource_ref,
                record.type,
                record.provider_ref,
                resource_availability_scope_ref(target.resource_ref),
            )
        )
    if len({binding.provider_ref.casefold() for binding in bindings}) != len(bindings):
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            True,
            "inventory_target_identity_mismatch",
        )
    try:
        latest, latest_revision = await settings.effective_values_with_revision()
    except Exception:  # noqa: BLE001 - a lost revision fence never selects a default policy
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            True,
            "runtime_settings_unavailable",
        )
    if latest_revision != revision or latest.get(RESOURCE_AVAILABILITY_SETTING_KEY) != raw:
        return ResourceAvailabilityAnalyzerBinding(
            (),
            revision,
            False,
            True,
            "runtime_settings_revision_changed",
        )
    source = InventoryResourceAvailabilitySource(
        inventory,
        bindings=tuple(bindings),
        state_reader=azure_resource_operational_state,
        supported_resource_types=AZURE_AVAILABILITY_RESOURCE_TYPES,
        expected_snapshot_id=inventory_generation,
        wall_clock=wall_clock,
    )
    grouped: dict[str, dict[str, ResourceAnalyzer]] = {}
    for target, binding in zip(selected, bindings, strict=True):
        declared = config.resources.get(target.resource_ref)
        policy = ResourceAvailabilityPolicy(
            resource_types=frozenset(config.resource_types),
            max_age_seconds=config.max_age_seconds,
            expected_state=ResourceOperationalState(declared.expected_state)
            if declared is not None and declared.expected_state is not None
            else None,
            expectation_ref=declared.reference
            if declared is not None and declared.expected_state is not None
            else None,
            planned_stops=tuple(
                PlannedStopWindow(
                    target.resource_ref,
                    window.since,
                    window.until,
                    window.reference,
                    window.maintenance,
                )
                for window in declared.planned_stops
            )
            if declared is not None
            else (),
        )
        leaf = ResourceAvailabilityAnalyzer(
            resource_kind=target.resource_kind,
            resource_type=binding.resource_type,
            scope_ref=binding.scope_ref,
            source=source,
            policy=policy,
            wall_clock=wall_clock,
        )
        grouped.setdefault(target.resource_kind, {})[target.resource_ref] = RecoveryAwareAnalyzer(
            leaf,
            state_store,
            ("resource_availability",),
        )
    return ResourceAvailabilityAnalyzerBinding(
        tuple(
            _TargetDispatchAvailabilityAnalyzer(kind, leaves, revision)
            for kind, leaves in grouped.items()
        ),
        revision,
        True,
        True,
        monitored_resources=len(bindings),
    )
