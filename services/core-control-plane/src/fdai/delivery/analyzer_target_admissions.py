"""Issue and retain decision-evidence admissions for analyzer target selection.

The analyzer target resolver (:mod:`fdai.delivery.analyzer_targets`) requires a
current ``analyzer-target-selection`` admission whenever an inventory-discovered
``Resource`` carries a generic ``state`` :class:`StateFactMetadata`. It never
verifies or admits itself.

This module provides the independent read-only state-fact verifier and durable
retention path that turns an eligible (observed, provider-authoritative,
complete, unconflicted, non-synthetic, unexpired) inventory state fact into a
verified :class:`DecisionCriticalEvidenceReceipt` and five-proof
:class:`DecisionEvidenceVerificationBundle`, evaluates them through
:class:`DecisionEvidenceReadinessGate` under a separated verifier identity, and
retains the resulting admission once in the shared :class:`StateStore` with an
atomic ``decision-evidence.admission-retained`` audit entry.

The resolver in :mod:`fdai.delivery.analyzer_targets` and
``assess_decision_evidence_admission`` remain unchanged and fail-closed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
    LiveEvidenceClaimRequirement,
    decision_critical_evidence_receipt_digest,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
    expected_verification_subjects,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.recorded_resource_state import (
    is_recorded_state_value_valid,
    operational_state_paths,
)

from fdai.core.investigation.analyzers import ANALYZER_KIND_BY_RESOURCE_TYPE
from fdai.core.readiness.decision_evidence import DecisionEvidenceReadinessGate
from fdai.delivery.analyzer_inventory import AnalyzerProviderReferenceReader
from fdai.delivery.analyzer_targets import (
    ANALYZER_TARGET_EVIDENCE_PURPOSE,
    INVENTORY_SCAN_LIMIT,
    RESOURCE_OBJECT_TYPE,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
    StateStoreDecisionEvidenceAdmissionRecorder,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceVerifierBinding,
    DecisionEvidenceVerifierRegistry,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.state_store import StateStore

DEFAULT_STATE_FACT_VERIFIER_ID = "inventory-state-fact-verifier"
DEFAULT_STATE_FACT_VERIFIER_VERSION = "1.0.0"
DEFAULT_STATE_FACT_TRUST_ANCHOR_ID = "anchor:inventory-state-fact-verifier"
DEFAULT_STATE_FACT_PRODUCER_ID = "inventory-state-fact-projector"
DEFAULT_STATE_FACT_PRODUCER_VERSION = "1.0.0"
DEFAULT_STATE_FACT_RECORDER_ID = "analyzer-target-admission-recorder"
STATE_FACT_AUTHORITY_CLASS = "provider_observed_state_fact"
STATE_FACT_METHOD_ID = "inventory-state-fact-readback"
STATE_FACT_METHOD_VERSION = "1.0.0"
STATE_FACT_FRESHNESS_POLICY_ID = "analyzer-target-state-fact-freshness"
STATE_FACT_FRESHNESS_POLICY_VERSION = "1.0.0"
_MAX_SYNCED_REVISIONS = 64


class AnalyzerInventoryProjectionReader(Protocol):
    """Read-only inventory projection query contract for state-fact verification."""

    async def query_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        object_ids: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        property_text_in: Mapping[str, Sequence[str]] | None = None,
        limit: int = 100,
        include_relationships: bool = True,
    ) -> OntologyGraphSnapshot: ...


class _CorroboratedStateFactBundleVerifier:
    """Recompute five-proof verification subjects from corroborated active-snapshot facts."""

    def __init__(
        self,
        *,
        candidate: _EligibleStateFactCandidate,
        verifier_id: str,
        verifier_version: str,
        trust_anchor_id: str,
        evaluated_at: datetime,
    ) -> None:
        self._candidate = candidate
        self._verifier_id = verifier_id
        self._verifier_version = verifier_version
        self._trust_anchor_id = trust_anchor_id
        self._evaluated_at = evaluated_at

    async def verify(
        self,
        receipt: DecisionCriticalEvidenceReceipt,
        *,
        trust_anchor_id: str,
    ) -> DecisionEvidenceVerificationBundle:
        if trust_anchor_id != self._trust_anchor_id:
            raise ValueError("state-fact verifier trust anchor does not match")
        candidate = self._candidate
        metadata = candidate.metadata
        if (
            candidate.corroborated_snapshot_id is not None
            and metadata.source_revision != candidate.corroborated_snapshot_id
        ):
            raise ValueError("state-fact source_revision does not match active snapshot")
        expected_evidence = content_digest(
            {
                "resource_id": candidate.resource_id,
                "state_fact": metadata.to_mapping(),
            }
        )
        expected_auth = content_digest(
            {
                "authority": metadata.authority.value,
                "corroborated_provider_ref": candidate.corroborated_provider_ref,
                "corroborated_snapshot_id": candidate.corroborated_snapshot_id,
                "evidence_refs": list(metadata.evidence_refs),
                "source_identity": metadata.source_identity,
                "source_revision": metadata.source_revision,
            }
        )
        expected_completeness = content_digest(
            {
                "completeness": metadata.completeness,
                "evidence_refs": list(metadata.evidence_refs),
                "resource_id": candidate.resource_id,
            }
        )
        expected_conflict = content_digest(
            {
                "conflicts": list(metadata.conflicts),
                "resource_id": candidate.resource_id,
                "source_revision": metadata.source_revision,
            }
        )
        expected_policy = content_digest(
            {
                "ceiling_seconds": metadata.freshness_ceiling_seconds,
                "policy_id": STATE_FACT_FRESHNESS_POLICY_ID,
                "policy_version": STATE_FACT_FRESHNESS_POLICY_VERSION,
            }
        )
        subjects = expected_verification_subjects(
            authentication_evidence_digest=expected_auth,
            evidence_digest=expected_evidence,
            completeness_evidence_digest=expected_completeness,
            conflict_evidence_digest=expected_conflict,
            freshness_policy_digest=expected_policy,
        )
        proofs = tuple(
            DecisionEvidenceVerificationProof(
                kind=kind,
                receipt_digest=receipt.receipt_digest,
                subject_digest=subject_digest,
                proof_digest=content_digest(
                    {
                        "corroborated_provider_ref": candidate.corroborated_provider_ref,
                        "corroborated_snapshot_id": candidate.corroborated_snapshot_id,
                        "kind": str(kind),
                        "receipt_digest": receipt.receipt_digest,
                        "subject_digest": subject_digest,
                        "verifier_id": self._verifier_id,
                    }
                ),
                verifier_id=self._verifier_id,
                verifier_version=self._verifier_version,
                trust_anchor_id=self._trust_anchor_id,
                issued_at=self._evaluated_at,
                valid_until=candidate.fresh_until,
            )
            for kind, subject_digest in subjects.items()
        )
        return DecisionEvidenceVerificationBundle.create(
            receipt_digest=receipt.receipt_digest,
            verifier_id=self._verifier_id,
            verifier_version=self._verifier_version,
            trust_anchor_id=self._trust_anchor_id,
            verified_at=self._evaluated_at,
            valid_until=candidate.fresh_until,
            proofs=proofs,
        )


@dataclass(frozen=True, slots=True)
class AnalyzerTargetAdmissionSyncReport:
    """Summary of one state-fact verification and admission-retention pass."""

    candidate_count: int
    eligible_count: int
    retained_count: int
    already_retained_count: int
    skipped_reason_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class _EligibleStateFactCandidate:
    resource_id: str
    resource_type: str
    metadata: StateFactMetadata
    fresh_until: datetime
    observed_state: str | None = None
    corroborated_snapshot_id: str | None = None
    corroborated_provider_ref: str | None = None


class AnalyzerTargetStateFactAdmissionIssuer:
    """Verify eligible inventory state facts and retain target-selection admissions.

    Each eligible ``Resource`` state fact must be a non-synthetic, unconflicted,
    complete (``completeness >= 1.0``), provider-authoritative observation in
    the ``observed`` lane whose ``evidence_cutoff`` is within its declared
    ``freshness_ceiling_seconds`` window at evaluation time. When
    ``provider_references`` is bound, every non-pod resource must also match an
    active inventory snapshot record with the same ``resource_id``,
    ``resource_type``, and a non-empty ``provider_ref``.

    Admissions are evaluated through :class:`DecisionEvidenceReadinessGate` under
    a verifier identity separated from both ``metadata.source_identity`` and
    ``producer_id``, and retained once via
    :class:`StateStoreDecisionEvidenceAdmissionRecorder` with an atomic
    ``decision-evidence.admission-retained`` shadow-mode audit entry.
    """

    def __init__(
        self,
        *,
        inventory_store: AnalyzerInventoryProjectionReader,
        state_store: StateStore,
        provider_references: AnalyzerProviderReferenceReader | None = None,
        analyzer_kinds: Mapping[str, str] = ANALYZER_KIND_BY_RESOURCE_TYPE,
        availability_resources: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
        verifier_id: str = DEFAULT_STATE_FACT_VERIFIER_ID,
        verifier_version: str = DEFAULT_STATE_FACT_VERIFIER_VERSION,
        trust_anchor_id: str = DEFAULT_STATE_FACT_TRUST_ANCHOR_ID,
        producer_id: str = DEFAULT_STATE_FACT_PRODUCER_ID,
        producer_version: str = DEFAULT_STATE_FACT_PRODUCER_VERSION,
        recorder_id: str = DEFAULT_STATE_FACT_RECORDER_ID,
    ) -> None:
        if (
            not verifier_id.strip()
            or not verifier_version.strip()
            or not trust_anchor_id.strip()
            or not producer_id.strip()
            or not producer_version.strip()
            or not recorder_id.strip()
            or verifier_id == producer_id
        ):
            raise ValueError(
                "state-fact admission issuer requires distinct non-empty producer and verifier"
            )
        self._inventory_store = inventory_store
        self._state_store = state_store
        self._provider_references = provider_references
        self._analyzer_kinds = dict(analyzer_kinds)
        self._availability_resources = dict(availability_resources or {})
        self._clock = clock or (lambda: datetime.now(UTC))
        self._verifier_id = verifier_id.strip()
        self._verifier_version = verifier_version.strip()
        self._trust_anchor_id = trust_anchor_id.strip()
        self._producer_id = producer_id.strip()
        self._producer_version = producer_version.strip()
        self._recorder = StateStoreDecisionEvidenceAdmissionRecorder(
            store=state_store,
            recorder_id=recorder_id.strip(),
            clock=self._clock,
        )

    async def issue_eligible(
        self,
        *,
        now: datetime | None = None,
    ) -> AnalyzerTargetAdmissionSyncReport:
        """Verify eligible inventory state facts and retain their admissions once."""

        evaluated_at = _aware_utc(now or self._clock())
        combined_kinds = {
            **self._analyzer_kinds,
            **{
                resource_type: "resource_availability"
                for resource_type in self._availability_resources.values()
                if resource_type not in self._analyzer_kinds
            },
        }
        snapshot = await self._inventory_store.query_objects(
            object_types=(RESOURCE_OBJECT_TYPE,),
            property_text_in={"type": tuple(sorted(combined_kinds))},
            limit=INVENTORY_SCAN_LIMIT,
            include_relationships=False,
        )
        if snapshot.truncated or snapshot.source_generation is None:
            return AnalyzerTargetAdmissionSyncReport(
                candidate_count=len(snapshot.objects),
                eligible_count=0,
                retained_count=0,
                already_retained_count=0,
                skipped_reason_counts=(("incomplete_inventory_projection", len(snapshot.objects)),)
                if snapshot.objects
                else (),
            )

        skipped: Counter[str] = Counter()
        candidates: list[_EligibleStateFactCandidate] = []
        for record in snapshot.objects:
            candidate = self._extract_eligible_candidate(
                record,
                evaluated_at=evaluated_at,
                analyzer_kinds=combined_kinds,
                skipped=skipped,
            )
            if candidate is not None:
                candidates.append(candidate)

        verified_candidates = await self._verify_provider_references(
            candidates,
            expected_snapshot_id=snapshot.source_generation,
            skipped=skipped,
        )

        retained_count = 0
        already_retained_count = 0
        eligible_count = 0
        for candidate in verified_candidates:
            outcome = await self._issue_and_retain(candidate, evaluated_at=evaluated_at)
            if outcome is None:
                skipped["gate_rejected"] += 1
                continue
            eligible_count += 1
            if outcome:
                retained_count += 1
            else:
                already_retained_count += 1

        return AnalyzerTargetAdmissionSyncReport(
            candidate_count=len(snapshot.objects),
            eligible_count=eligible_count,
            retained_count=retained_count,
            already_retained_count=already_retained_count,
            skipped_reason_counts=tuple(sorted(skipped.items())),
        )

    def _extract_eligible_candidate(
        self,
        record: OntologyObjectRecord,
        *,
        evaluated_at: datetime,
        analyzer_kinds: Mapping[str, str],
        skipped: Counter[str],
    ) -> _EligibleStateFactCandidate | None:
        resource_id = record.properties.get("id")
        resource_type = record.properties.get("type")
        if not isinstance(resource_id, str) or not isinstance(resource_type, str):
            skipped["malformed_resource"] += 1
            return None
        normalized_id = resource_id.strip()
        normalized_type = resource_type.strip()
        if not normalized_id or not normalized_type:
            skipped["malformed_resource"] += 1
            return None
        analyzer_kind = analyzer_kinds.get(normalized_type)
        availability_selected = self._availability_resources.get(normalized_id) == normalized_type
        if analyzer_kind is None or (
            analyzer_kind == "resource_availability" and not availability_selected
        ):
            skipped["unmapped_resource_type"] += 1
            return None
        provider_properties = record.properties.get("properties")
        raw = (
            provider_properties.get(STATE_FACT_METADATA_PROPERTY)
            if isinstance(provider_properties, Mapping)
            else None
        )
        if raw is None:
            skipped["no_state_fact"] += 1
            return None
        if not isinstance(raw, Mapping):
            skipped["unusable_state_fact"] += 1
            return None
        if "lane" in raw:
            metadata_value = raw
        elif "state" not in raw:
            skipped["no_state_fact"] += 1
            return None
        else:
            metadata_value = raw["state"]
            if not isinstance(metadata_value, Mapping):
                skipped["unusable_state_fact"] += 1
                return None
        try:
            metadata = StateFactMetadata.from_mapping(metadata_value)
        except (TypeError, ValueError):
            skipped["unusable_state_fact"] += 1
            return None
        if (
            metadata.lane is not StateFactLane.OBSERVED
            or metadata.authority is not StateFactAuthority.PROVIDER
            or metadata.synthetic
            or metadata.conflicts
            or metadata.completeness < 1.0
            or metadata.evidence_cutoff.tzinfo is None
            or metadata.recorded_at.tzinfo is None
            or metadata.effective_at.tzinfo is None
            or not metadata.evidence_refs
            or not metadata.source_identity.strip()
            or not metadata.source_revision.strip()
            or metadata.source_identity.strip() in {self._verifier_id, self._producer_id}
        ):
            skipped["unusable_state_fact"] += 1
            return None
        age_seconds = (evaluated_at - metadata.evidence_cutoff).total_seconds()
        fresh_until = metadata.evidence_cutoff + timedelta(
            seconds=metadata.freshness_ceiling_seconds
        )
        if (
            age_seconds < 0
            or age_seconds > metadata.freshness_ceiling_seconds
            or fresh_until <= evaluated_at
        ):
            skipped["stale_state_fact"] += 1
            return None
        raw_observed_state = (
            provider_properties.get("state") if isinstance(provider_properties, Mapping) else None
        )
        observed_state = (
            raw_observed_state.strip()
            if isinstance(raw_observed_state, str) and raw_observed_state.strip()
            else None
        )
        return _EligibleStateFactCandidate(
            resource_id=normalized_id,
            resource_type=normalized_type,
            metadata=metadata,
            fresh_until=_aware_utc(fresh_until),
            observed_state=observed_state,
        )

    async def _verify_provider_references(
        self,
        candidates: list[_EligibleStateFactCandidate],
        *,
        expected_snapshot_id: str | None,
        skipped: Counter[str],
    ) -> list[_EligibleStateFactCandidate]:
        if not candidates:
            return []
        non_pod_candidates: list[_EligibleStateFactCandidate] = []
        for candidate in candidates:
            if candidate.resource_type == "kubernetes.pod":
                skipped["unverified_provider_identity"] += 1
            else:
                non_pod_candidates.append(candidate)
        if not non_pod_candidates:
            return []
        if self._provider_references is None:
            skipped["provider_identity_unavailable"] += len(non_pod_candidates)
            return []
        non_pod_ids = tuple(sorted({item.resource_id for item in non_pod_candidates}))
        try:
            snapshot_id, active_resources = await self._provider_references.read_active_resources(
                resource_ids=non_pod_ids
            )
        except Exception:  # noqa: BLE001 - unreadable active snapshot refuses issuance
            skipped["provider_identity_unavailable"] += len(non_pod_candidates)
            return []
        if (
            snapshot_id is None
            or not snapshot_id.strip()
            or (expected_snapshot_id is not None and snapshot_id != expected_snapshot_id)
        ):
            skipped["provider_snapshot_mismatch"] += len(non_pod_candidates)
            return []
        normalized_snapshot_id = snapshot_id.strip()
        expected_generation_ref = f"inventory-generation:{normalized_snapshot_id}"
        verified: list[_EligibleStateFactCandidate] = []
        seen_provider_refs: set[str] = set()
        for candidate in non_pod_candidates:
            active = active_resources.get(candidate.resource_id)
            if (
                active is None
                or active.resource_id != candidate.resource_id
                or active.type.strip() != candidate.resource_type
                or active.provider_ref is None
                or not active.provider_ref.strip()
            ):
                skipped["unverified_provider_identity"] += 1
                continue
            if (
                candidate.metadata.source_revision != normalized_snapshot_id
                or expected_generation_ref not in candidate.metadata.evidence_refs
                or not _corroborates_active_resource(candidate, active)
            ):
                skipped["unverified_state_fact_corroboration"] += 1
                continue
            provider_ref = active.provider_ref.strip()
            folded_ref = provider_ref.casefold()
            if folded_ref in seen_provider_refs:
                skipped["ambiguous_provider_identity"] += 1
                continue
            seen_provider_refs.add(folded_ref)
            verified.append(
                _EligibleStateFactCandidate(
                    resource_id=candidate.resource_id,
                    resource_type=candidate.resource_type,
                    metadata=candidate.metadata,
                    fresh_until=candidate.fresh_until,
                    observed_state=candidate.observed_state,
                    corroborated_snapshot_id=normalized_snapshot_id,
                    corroborated_provider_ref=provider_ref,
                )
            )
        return verified

    async def _issue_and_retain(
        self,
        candidate: _EligibleStateFactCandidate,
        *,
        evaluated_at: datetime,
    ) -> bool | None:
        metadata = candidate.metadata
        evidence_digest = content_digest(
            {
                "resource_id": candidate.resource_id,
                "state_fact": metadata.to_mapping(),
            }
        )
        scope_digest = content_digest(
            {
                "resource_id": candidate.resource_id,
                "resource_type": candidate.resource_type,
            }
        )
        policy_digest = content_digest(
            {
                "ceiling_seconds": metadata.freshness_ceiling_seconds,
                "policy_id": STATE_FACT_FRESHNESS_POLICY_ID,
                "policy_version": STATE_FACT_FRESHNESS_POLICY_VERSION,
            }
        )
        auth_digest = content_digest(
            {
                "authority": metadata.authority.value,
                "corroborated_provider_ref": candidate.corroborated_provider_ref,
                "corroborated_snapshot_id": candidate.corroborated_snapshot_id,
                "evidence_refs": list(metadata.evidence_refs),
                "source_identity": metadata.source_identity,
                "source_revision": metadata.source_revision,
            }
        )
        provenance_digest = content_digest(
            {
                "evidence_refs": list(metadata.evidence_refs),
                "recorded_at": _aware_utc(metadata.recorded_at).isoformat(),
                "source_identity": metadata.source_identity,
                "source_revision": metadata.source_revision,
            }
        )
        completeness_digest = content_digest(
            {
                "completeness": metadata.completeness,
                "evidence_refs": list(metadata.evidence_refs),
                "resource_id": candidate.resource_id,
            }
        )
        conflict_digest = content_digest(
            {
                "conflicts": list(metadata.conflicts),
                "resource_id": candidate.resource_id,
                "source_revision": metadata.source_revision,
            }
        )
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "authority_class": STATE_FACT_AUTHORITY_CLASS,
            "source_identity": metadata.source_identity,
            "authentication_evidence_digest": auth_digest,
            "scope_digest": scope_digest,
            "purpose_id": ANALYZER_TARGET_EVIDENCE_PURPOSE,
            "producer_id": self._producer_id,
            "producer_version": self._producer_version,
            "method_id": STATE_FACT_METHOD_ID,
            "method_version": STATE_FACT_METHOD_VERSION,
            "source_revision": metadata.source_revision,
            "evidence_digest": evidence_digest,
            "provenance_digest": provenance_digest,
            "event_at": _aware_utc(metadata.effective_at),
            "evidence_cutoff": _aware_utc(metadata.evidence_cutoff),
            "recorded_at": _aware_utc(metadata.recorded_at),
            "fresh_until": candidate.fresh_until,
            "freshness_policy_id": STATE_FACT_FRESHNESS_POLICY_ID,
            "freshness_policy_version": STATE_FACT_FRESHNESS_POLICY_VERSION,
            "freshness_policy_digest": policy_digest,
            "freshness_ceiling_seconds": metadata.freshness_ceiling_seconds,
            "completeness_basis_points": 10_000,
            "completeness_evidence_digest": completeness_digest,
            "conflict_status": EvidenceConflictStatus.CLEAR,
            "conflict_evidence_digest": conflict_digest,
            "conflict_evidence_digests": (),
            "synthetic": False,
            "execution_authority": False,
        }
        receipt = DecisionCriticalEvidenceReceipt.model_validate(
            {
                **values,
                "receipt_digest": decision_critical_evidence_receipt_digest(**values),
            }
        )
        binding = DecisionEvidenceVerifierBinding(
            authority_class=STATE_FACT_AUTHORITY_CLASS,
            method_id=STATE_FACT_METHOD_ID,
            verifier_id=self._verifier_id,
            verifier_version=self._verifier_version,
            trust_anchor_id=self._trust_anchor_id,
            verifier=_CorroboratedStateFactBundleVerifier(
                candidate=candidate,
                verifier_id=self._verifier_id,
                verifier_version=self._verifier_version,
                trust_anchor_id=self._trust_anchor_id,
                evaluated_at=evaluated_at,
            ),
        )
        gate = DecisionEvidenceReadinessGate(registry=DecisionEvidenceVerifierRegistry((binding,)))
        requirement = LiveEvidenceClaimRequirement(
            allowed_authority_classes=(STATE_FACT_AUTHORITY_CLASS,),
            allowed_source_identities=(metadata.source_identity,),
            scope_digest=scope_digest,
            purpose_id=ANALYZER_TARGET_EVIDENCE_PURPOSE,
            producer_id=self._producer_id,
            producer_version=self._producer_version,
            method_id=STATE_FACT_METHOD_ID,
            method_version=STATE_FACT_METHOD_VERSION,
            source_revision=metadata.source_revision,
            freshness_policy_digest=policy_digest,
            freshness_ceiling_seconds=metadata.freshness_ceiling_seconds,
            minimum_completeness_basis_points=10_000,
        )
        result = await gate.evaluate(receipt, requirement, evaluated_at=evaluated_at)
        if not result.eligible:
            return None
        return await self._recorder.retain(receipt, result)


class AnalyzerTargetDecisionEvidenceAdmissionProvider(StateStoreDecisionEvidenceAdmissionProvider):
    """Resolve retained target-selection admissions and issue eligible state-fact records once."""

    def __init__(
        self,
        *,
        store: StateStore,
        issuer: AnalyzerTargetStateFactAdmissionIssuer | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(store=store, clock=clock)
        self._issuer = issuer
        self._synced_revisions: set[str] = set()

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission | None:
        existing = await super().admit(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
        )
        if existing is not None:
            return existing
        if (
            purpose_id == ANALYZER_TARGET_EVIDENCE_PURPOSE
            and self._issuer is not None
            and source_revision not in self._synced_revisions
            and len(self._synced_revisions) < _MAX_SYNCED_REVISIONS
        ):
            self._synced_revisions.add(source_revision)
            await self._issuer.issue_eligible(now=self._clock())
            return await super().admit(
                evidence_digest=evidence_digest,
                scope_digest=scope_digest,
                purpose_id=purpose_id,
                source_revision=source_revision,
            )
        return None

    async def aclose(self) -> None:
        """Close owned store resources when overridden by a composition wrapper."""


def _corroborates_active_resource(
    candidate: _EligibleStateFactCandidate,
    active: Any,
) -> bool:
    metadata = candidate.metadata
    last_seen = getattr(active, "last_seen", None)
    if isinstance(last_seen, datetime):
        parsed_last_seen = last_seen
    elif isinstance(last_seen, str) and last_seen.strip():
        try:
            parsed_last_seen = datetime.fromisoformat(last_seen.strip())
        except ValueError:
            return False
    else:
        return False
    if (
        parsed_last_seen.tzinfo is None
        or _aware_utc(parsed_last_seen) != _aware_utc(metadata.evidence_cutoff)
        or _aware_utc(parsed_last_seen) != _aware_utc(metadata.effective_at)
        or _aware_utc(parsed_last_seen) != _aware_utc(metadata.recorded_at)
    ):
        return False
    props = getattr(active, "props", None)
    if not isinstance(props, Mapping):
        return False
    if STATE_FACT_METADATA_PROPERTY in props:
        raw_active = props.get(STATE_FACT_METADATA_PROPERTY)
        if not isinstance(raw_active, Mapping):
            return False
        if "lane" in raw_active or "state" in raw_active:
            active_meta_map = raw_active if "lane" in raw_active else raw_active.get("state")
            if not isinstance(active_meta_map, Mapping):
                return False
            try:
                active_metadata = StateFactMetadata.from_mapping(active_meta_map)
            except (TypeError, ValueError):
                return False
            return active_metadata == metadata
    if props.get("observation_conflicts"):
        return False
    if metadata.source_identity != "inventory-provider":
        return False
    paths = operational_state_paths(candidate.resource_type)
    if not paths:
        return False
    observed_values: list[str] = []
    for prefix in ("", "properties.", "properties.properties."):
        for path in paths:
            current: object = props
            for part in (prefix + path).split("."):
                if not isinstance(current, Mapping):
                    current = None
                    break
                current = current.get(part)
            if is_recorded_state_value_valid(
                current,
                allow_unknown=path == "ready_status",
            ) and isinstance(current, str):
                stripped = current.strip()
                if stripped not in observed_values:
                    observed_values.append(stripped)
    if len(observed_values) != 1:
        return False
    if candidate.observed_state is None or candidate.observed_state != observed_values[0]:
        return False
    return True


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("analyzer target admission timestamps MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "DEFAULT_STATE_FACT_PRODUCER_ID",
    "DEFAULT_STATE_FACT_PRODUCER_VERSION",
    "DEFAULT_STATE_FACT_RECORDER_ID",
    "DEFAULT_STATE_FACT_TRUST_ANCHOR_ID",
    "DEFAULT_STATE_FACT_VERIFIER_ID",
    "DEFAULT_STATE_FACT_VERIFIER_VERSION",
    "STATE_FACT_AUTHORITY_CLASS",
    "STATE_FACT_FRESHNESS_POLICY_ID",
    "STATE_FACT_FRESHNESS_POLICY_VERSION",
    "STATE_FACT_METHOD_ID",
    "STATE_FACT_METHOD_VERSION",
    "AnalyzerTargetAdmissionSyncReport",
    "AnalyzerTargetDecisionEvidenceAdmissionProvider",
    "AnalyzerTargetStateFactAdmissionIssuer",
]
