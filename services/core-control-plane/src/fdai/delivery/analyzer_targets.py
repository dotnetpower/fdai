"""Resolve analyzer-tick targets from configuration and the durable inventory.

The scheduled tick used to analyze only the resources an operator pinned in
``FDAI_ANALYZER_TARGETS``. A newly discovered resource therefore stayed
unobserved until someone edited a deployment variable. This module resolves the
same tick's targets from the durable inventory projection as well, so a
supported resource that the inventory already observed joins the next tick
without a deployment edit.

Resolution is read-only and grants no execution authority. It fails closed:

- a projection read failure raises :class:`AnalyzerTargetResolutionError`
  instead of silently degrading to the configured list, so the job retries;
- a resource whose observed state fact is stale, conflicting, incomplete, or
  synthetic is skipped with a stable reason rather than analyzed on unusable
  evidence;
- a resource type with no reviewed analyzer mapping is skipped, never guessed.

A projected ``Resource`` without a state fact carries an observed identity and
type but no state claim. Target selection needs identity and type only, so such
a resource is eligible; the analyzer's own findings carry their evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from fdai.core.investigation.analyzers import ANALYZER_KIND_BY_RESOURCE_TYPE
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

RESOURCE_OBJECT_TYPE = "Resource"
DEFAULT_MAX_DISCOVERED = 200
_MAX_DISCOVERED_CEILING = 1_000

SKIP_UNMAPPED_RESOURCE_TYPE = "unmapped_resource_type"
SKIP_MALFORMED_RESOURCE = "malformed_resource"
SKIP_UNUSABLE_STATE_FACT = "unusable_state_fact"
SKIP_STALE_STATE_FACT = "stale_state_fact"


class AnalyzerTargetResolutionError(RuntimeError):
    """The durable inventory projection could not be read for this tick."""


@dataclass(frozen=True, slots=True)
class AnalyzerTargetResolution:
    """One tick's resolved targets and the reason every candidate was dropped.

    ``inventory_consulted`` is ``False`` when no durable projection was bound,
    so a reader never mistakes "no store" for "the store observed nothing".
    ``truncated`` reports that the projection held more eligible resources than
    ``max_discovered`` allowed; the retained selection stays deterministic.
    """

    targets: tuple[AnalyzerTarget, ...]
    configured: int
    discovered: int
    inventory_consulted: bool
    skipped_reasons: tuple[str, ...] = ()
    truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "discovered": self.discovered,
            "inventory_consulted": self.inventory_consulted,
            "skipped_reasons": list(self.skipped_reasons),
            "truncated": self.truncated,
        }


async def resolve_analyzer_targets(
    *,
    configured: Sequence[AnalyzerTarget],
    store: OntologyInstanceStore | None,
    now: datetime,
    analyzer_kinds: Mapping[str, str] = ANALYZER_KIND_BY_RESOURCE_TYPE,
    max_discovered: int = DEFAULT_MAX_DISCOVERED,
) -> AnalyzerTargetResolution:
    """Return the configured targets plus every eligible inventory-backed one.

    Configured targets are preserved in their declared order and always win a
    duplicate; discovered targets follow in ascending ``resource_ref`` order so
    two ticks over one projection resolve the same list.

    Args:
        configured: Operator-pinned targets, already parsed and deduplicated.
        store: The durable inventory projection, or ``None`` when unbound.
        now: Timezone-aware evaluation time used for freshness only.
        analyzer_kinds: Reviewed neutral ``resource type -> analyzer kind`` map.
        max_discovered: Upper bound on inventory-backed targets for one tick.

    Raises:
        ValueError: ``now`` is naive or ``max_discovered`` is out of bounds.
        AnalyzerTargetResolutionError: the projection read failed.
    """
    if now.tzinfo is None:
        raise ValueError("resolve_analyzer_targets requires a timezone-aware now")
    if not 1 <= max_discovered <= _MAX_DISCOVERED_CEILING:
        raise ValueError(f"max_discovered MUST be in [1, {_MAX_DISCOVERED_CEILING}]")

    ordered: list[AnalyzerTarget] = []
    seen: set[str] = set()
    for target in configured:
        if target.resource_ref in seen:
            continue
        seen.add(target.resource_ref)
        ordered.append(target)
    configured_count = len(ordered)

    if store is None:
        return AnalyzerTargetResolution(
            targets=tuple(ordered),
            configured=configured_count,
            discovered=0,
            inventory_consulted=False,
        )

    try:
        snapshot = await store.query_objects(
            object_types=(RESOURCE_OBJECT_TYPE,),
            limit=max_discovered + 1,
        )
    except Exception as exc:  # noqa: BLE001 - an unreadable projection MUST retry, not degrade
        raise AnalyzerTargetResolutionError(
            f"durable inventory projection read failed: {type(exc).__name__}"
        ) from exc

    skipped: set[str] = set()
    eligible: list[AnalyzerTarget] = []
    for record in snapshot.objects:
        candidate = _eligible_target(
            record,
            now=now,
            analyzer_kinds=analyzer_kinds,
            skipped=skipped,
        )
        if candidate is not None:
            eligible.append(candidate)

    eligible.sort(key=lambda item: (item.resource_ref, item.resource_kind))
    truncated = snapshot.truncated or len(eligible) > max_discovered
    discovered = 0
    for target in eligible:
        if discovered >= max_discovered:
            break
        if target.resource_ref in seen:
            continue
        seen.add(target.resource_ref)
        ordered.append(target)
        discovered += 1

    return AnalyzerTargetResolution(
        targets=tuple(ordered),
        configured=configured_count,
        discovered=discovered,
        inventory_consulted=True,
        skipped_reasons=tuple(sorted(skipped)),
        truncated=truncated,
    )


def _eligible_target(
    record: OntologyObjectRecord,
    *,
    now: datetime,
    analyzer_kinds: Mapping[str, str],
    skipped: set[str],
) -> AnalyzerTarget | None:
    """Return one analyzable target, or ``None`` with a recorded skip reason."""
    resource_id = record.properties.get("id")
    resource_type = record.properties.get("type")
    if not isinstance(resource_id, str) or not isinstance(resource_type, str):
        skipped.add(SKIP_MALFORMED_RESOURCE)
        return None
    resource_id = resource_id.strip()
    if not resource_id:
        skipped.add(SKIP_MALFORMED_RESOURCE)
        return None
    analyzer_kind = analyzer_kinds.get(resource_type.strip())
    if analyzer_kind is None:
        skipped.add(SKIP_UNMAPPED_RESOURCE_TYPE)
        return None
    if not _state_fact_supports_selection(record, now=now, skipped=skipped):
        return None
    return AnalyzerTarget(resource_ref=resource_id, resource_kind=analyzer_kind)


def _state_fact_supports_selection(
    record: OntologyObjectRecord,
    *,
    now: datetime,
    skipped: set[str],
) -> bool:
    """Report whether the recorded observation still supports selecting a target.

    An absent state fact is eligible: the projection observed identity and type
    without asserting state. A present state fact MUST be an unconflicted,
    complete, non-synthetic provider observation inside its freshness ceiling.
    """
    provider_properties = record.properties.get("properties")
    if not isinstance(provider_properties, Mapping):
        return True
    raw = provider_properties.get(STATE_FACT_METADATA_PROPERTY)
    if raw is None:
        return True
    if not isinstance(raw, Mapping):
        skipped.add(SKIP_UNUSABLE_STATE_FACT)
        return False
    try:
        metadata = StateFactMetadata.from_mapping(raw)
    except (ValueError, TypeError):
        skipped.add(SKIP_UNUSABLE_STATE_FACT)
        return False
    if (
        metadata.lane is not StateFactLane.OBSERVED
        or metadata.authority is not StateFactAuthority.PROVIDER
        or metadata.synthetic
        or metadata.conflicts
        or metadata.completeness < 1.0
    ):
        skipped.add(SKIP_UNUSABLE_STATE_FACT)
        return False
    age_seconds = (now - metadata.evidence_cutoff).total_seconds()
    if age_seconds > metadata.freshness_ceiling_seconds:
        skipped.add(SKIP_STALE_STATE_FACT)
        return False
    return True


__all__ = [
    "DEFAULT_MAX_DISCOVERED",
    "RESOURCE_OBJECT_TYPE",
    "SKIP_MALFORMED_RESOURCE",
    "SKIP_STALE_STATE_FACT",
    "SKIP_UNMAPPED_RESOURCE_TYPE",
    "SKIP_UNUSABLE_STATE_FACT",
    "AnalyzerTargetResolution",
    "AnalyzerTargetResolutionError",
    "resolve_analyzer_targets",
]
