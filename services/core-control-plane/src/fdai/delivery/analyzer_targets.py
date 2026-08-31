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
- a resource whose state fact lacks a current independent decision-evidence
  admission is skipped instead of entering analyzer selection;
- a resource type with no reviewed analyzer mapping is skipped, never guessed.

A projected ``Resource`` without a state fact carries an observed identity and
type but no state claim. Target selection needs identity and type only, so such
a resource is eligible; the analyzer's own findings carry their evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.investigation.analyzers import ANALYZER_KIND_BY_RESOURCE_TYPE
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)
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
#: One below the durable store's own 1,000-row query bound, because resolution
#: asks for one extra row to detect truncation.
MAX_DISCOVERED_CEILING = 999

SKIP_UNMAPPED_RESOURCE_TYPE = "unmapped_resource_type"
SKIP_MALFORMED_RESOURCE = "malformed_resource"
SKIP_UNUSABLE_STATE_FACT = "unusable_state_fact"
SKIP_STALE_STATE_FACT = "stale_state_fact"
SKIP_UNVERIFIED_STATE_FACT = "unverified_state_fact"
ANALYZER_TARGET_EVIDENCE_PURPOSE = "analyzer-target-selection"
ANALYZER_TARGET_IDENTITY_EVIDENCE_PURPOSE = "analyzer-target-identity"


class AnalyzerTargetResolutionError(RuntimeError):
    """The durable inventory projection could not be read for this tick."""


@dataclass(frozen=True, slots=True)
class AnalyzerTargetResolution:
    """One tick's resolved targets and the reason every candidate was dropped.

    ``inventory_consulted`` is ``False`` when no durable projection was bound,
    so a reader never mistakes "no store" for "the store observed nothing".
    ``truncated`` reports that more resources were available than this tick
    accepted, either because the projection page itself was truncated or
    because more eligible resources were returned than ``max_discovered``
    allowed. Ordering inside one returned page is deterministic; which page a
    truncated projection returns is the store's decision, so a truncated tick
    is not guaranteed to select the same subset as the previous one.
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
    decision_evidence: DecisionEvidenceAdmissionProvider | None = None,
) -> AnalyzerTargetResolution:
    """Return the configured targets plus every eligible inventory-backed one.

    Configured targets are preserved in their declared order and always win a
    duplicate; discovered targets follow in ascending ``resource_ref`` order so
    two ticks over one untruncated projection resolve the same list.

    Args:
        configured: Operator-pinned targets, already parsed and deduplicated.
        store: The durable inventory projection, or ``None`` when unbound.
        now: Timezone-aware evaluation time used for freshness only.
        analyzer_kinds: Reviewed neutral ``resource type -> analyzer kind`` map.
        max_discovered: Upper bound on inventory-backed targets for one tick.
        decision_evidence: Trusted admission provider, or ``None`` to reject
            discovered targets that carry state facts.

    Raises:
        ValueError: ``now`` is naive or ``max_discovered`` is out of bounds.
        AnalyzerTargetResolutionError: the projection read failed.
    """
    if now.tzinfo is None:
        raise ValueError("resolve_analyzer_targets requires a timezone-aware now")
    if not 1 <= max_discovered <= MAX_DISCOVERED_CEILING:
        raise ValueError(f"max_discovered MUST be in [1, {MAX_DISCOVERED_CEILING}]")

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
        candidate = await _eligible_target(
            record,
            now=now,
            analyzer_kinds=analyzer_kinds,
            skipped=skipped,
            decision_evidence=decision_evidence,
        )
        if candidate is not None:
            eligible.append(candidate)

    eligible.sort(key=lambda item: (item.resource_ref, item.resource_kind))
    discovered = 0
    withheld = False
    for target in eligible:
        if discovered >= max_discovered:
            withheld = True
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
        truncated=snapshot.truncated or withheld,
    )


async def _eligible_target(
    record: OntologyObjectRecord,
    *,
    now: datetime,
    analyzer_kinds: Mapping[str, str],
    skipped: set[str],
    decision_evidence: DecisionEvidenceAdmissionProvider | None,
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
    if not await _state_fact_supports_selection(
        record,
        resource_id=resource_id,
        resource_type=resource_type,
        now=now,
        skipped=skipped,
        decision_evidence=decision_evidence,
    ):
        return None
    return AnalyzerTarget(resource_ref=resource_id, resource_kind=analyzer_kind)


async def _state_fact_supports_selection(
    record: OntologyObjectRecord,
    *,
    resource_id: str,
    resource_type: str,
    now: datetime,
    skipped: set[str],
    decision_evidence: DecisionEvidenceAdmissionProvider | None,
) -> bool:
    """Report whether the recorded observation still supports selecting a target.

    Selection is a positive decision boundary in both shapes, so each shape has
    its own registered admission. A present state fact MUST be an unconflicted,
    complete, non-synthetic provider observation with a timezone-aware evidence
    cutoff inside its freshness ceiling, admitted under
    ``ANALYZER_TARGET_EVIDENCE_PURPOSE``. An absent state fact asserts identity
    and type only, and is delegated to the identity boundary so that no eligible
    target can be selected without an admission.
    """
    provider_properties = record.properties.get("properties")
    raw = (
        provider_properties.get(STATE_FACT_METADATA_PROPERTY)
        if isinstance(provider_properties, Mapping)
        else None
    )
    if raw is None:
        return await _identity_supports_selection(
            record,
            resource_id=resource_id,
            resource_type=resource_type,
            now=now,
            skipped=skipped,
            decision_evidence=decision_evidence,
        )
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
    if metadata.evidence_cutoff.tzinfo is None:
        skipped.add(SKIP_UNUSABLE_STATE_FACT)
        return False
    age_seconds = (now - metadata.evidence_cutoff).total_seconds()
    if age_seconds < 0 or age_seconds > metadata.freshness_ceiling_seconds:
        skipped.add(SKIP_STALE_STATE_FACT)
        return False
    if decision_evidence is None:
        skipped.add(SKIP_UNVERIFIED_STATE_FACT)
        return False
    evidence_digest = content_digest(
        {
            "resource_id": resource_id,
            "state_fact": metadata.to_mapping(),
        }
    )
    scope_digest = content_digest(
        {
            "resource_id": resource_id,
            "resource_type": resource_type,
        }
    )
    admission = await decision_evidence.admit(
        evidence_digest=evidence_digest,
        scope_digest=scope_digest,
        purpose_id=ANALYZER_TARGET_EVIDENCE_PURPOSE,
        source_revision=metadata.source_revision,
    )
    if admission is None or assess_decision_evidence_admission(
        admission,
        expected_evidence_digest=evidence_digest,
        expected_scope_digest=scope_digest,
        expected_purpose_id=ANALYZER_TARGET_EVIDENCE_PURPOSE,
        expected_source_revision=metadata.source_revision,
        evaluated_at=now,
    ):
        skipped.add(SKIP_UNVERIFIED_STATE_FACT)
        return False
    return True


async def _identity_supports_selection(
    record: OntologyObjectRecord,
    *,
    resource_id: str,
    resource_type: str,
    now: datetime,
    skipped: set[str],
    decision_evidence: DecisionEvidenceAdmissionProvider | None,
) -> bool:
    """Report whether identity-and-type-only observation may select a target.

    The projection asserted no state, so the only evidence is the observed
    identity, type, and projection revision. Selecting on that is still a
    positive decision, so it requires its own current shared admission bound to
    that exact triple. An unbound provider or a mismatched admission fails
    closed and drops the candidate.
    """

    if decision_evidence is None:
        skipped.add(SKIP_UNVERIFIED_STATE_FACT)
        return False
    evidence_digest = content_digest(
        {
            "resource_id": resource_id,
            "resource_type": resource_type,
            "object_type": record.object_type,
            "revision": record.revision,
        }
    )
    scope_digest = content_digest(
        {
            "resource_id": resource_id,
            "resource_type": resource_type,
        }
    )
    source_revision = f"ontology-object-revision:{record.revision}"
    admission = await decision_evidence.admit(
        evidence_digest=evidence_digest,
        scope_digest=scope_digest,
        purpose_id=ANALYZER_TARGET_IDENTITY_EVIDENCE_PURPOSE,
        source_revision=source_revision,
    )
    if admission is None or assess_decision_evidence_admission(
        admission,
        expected_evidence_digest=evidence_digest,
        expected_scope_digest=scope_digest,
        expected_purpose_id=ANALYZER_TARGET_IDENTITY_EVIDENCE_PURPOSE,
        expected_source_revision=source_revision,
        evaluated_at=now,
    ):
        skipped.add(SKIP_UNVERIFIED_STATE_FACT)
        return False
    return True


__all__ = [
    "DEFAULT_MAX_DISCOVERED",
    "MAX_DISCOVERED_CEILING",
    "RESOURCE_OBJECT_TYPE",
    "SKIP_MALFORMED_RESOURCE",
    "SKIP_STALE_STATE_FACT",
    "SKIP_UNMAPPED_RESOURCE_TYPE",
    "SKIP_UNUSABLE_STATE_FACT",
    "SKIP_UNVERIFIED_STATE_FACT",
    "ANALYZER_TARGET_EVIDENCE_PURPOSE",
    "ANALYZER_TARGET_IDENTITY_EVIDENCE_PURPOSE",
    "AnalyzerTargetResolution",
    "AnalyzerTargetResolutionError",
    "resolve_analyzer_targets",
]
