"""Observe the deployed observation lifecycle the OI-16 campaign must certify.

Duplicate delivery, late arrival, resource re-creation, and cross-release schema
replay are all properties of the *journal*, not of the metadata a fixture could
write beside it. Each probe here therefore drives or reads the real deployed path:
the normalized journal adapter, the lifecycle binder that owns partitions and
incarnations, the scope-bounded correction closure, and the canonical schema replay
function the provider contract exports.

No probe writes a partition, an incarnation, or a correction receipt directly, and
no probe advances a global projection watermark. A scenario whose deployed evidence
cannot be reached fails closed to an explicit unavailable outcome.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationCorrectionReceipt,
    ObservationPartition,
    ObservationPartitionKind,
    ResourceIncarnation,
)
from fdai.delivery.operational_history_certification_campaign import (
    CampaignBinding,
    ScenarioObservation,
    evidence_digest,
    scenario_check,
)
from fdai.delivery.operational_history_certification_campaign_observations import (
    PRIOR_SCHEMA_VERSION,
    CampaignObservationJournal,
    SyntheticSlot,
    cross_release_stable_body,
    current_schema_record,
    full_observation,
    incarnation_lifecycle,
    late_observation,
    prior_schema_record,
    synthetic_resource_ref,
)
from fdai.shared.providers.inventory_observation import (
    INVENTORY_OBSERVATION_SCHEMA_VERSION,
    replay_inventory_observation_schema,
)

_LOGGER = logging.getLogger("fdai.operational_history_certification_campaign.lifecycle_probes")


class LifecycleHistoryStore(Protocol):
    """The bounded write and read surface these lifecycle probes depend on."""

    async def resolve_evidence_partitions(
        self, evidence_refs: tuple[str, ...]
    ) -> tuple[str, ...]: ...

    async def list_incarnations(
        self, resource_ref: str, *, limit: int = 16
    ) -> tuple[ResourceIncarnation, ...]: ...

    async def latest_correction(
        self, correction_partition_id: str
    ) -> ObservationCorrectionReceipt | None: ...

    async def close_scope_corrections(
        self,
        *,
        scope_ref: str,
        generation: str,
        projection_watermark: int,
        closed_at: datetime,
    ) -> None: ...


class LifecycleRecordReader(Protocol):
    """Read the exact persisted records bound to one partition."""

    async def archive_records(self, partition_id: str) -> tuple[Mapping[str, object], ...]: ...


def _unobserved(scenario: OperationalHistoryScenario, reason: str) -> ScenarioObservation:
    return ScenarioObservation(scenario=scenario, unavailable_reason=reason)


async def observe_duplicate_delivery(
    *,
    binding: CampaignBinding,
    journal: CampaignObservationJournal,
    history: LifecycleHistoryStore,
    partitions: Sequence[ObservationPartition],
) -> ScenarioObservation:
    """Redeliver one exact normalized observation and prove both deltas are zero.

    The probe replays the identical content-addressed record through the deployed
    journal, so suppression is proven by the journal's own insert count rather than by
    re-writing a partition row. A second insert, a moved high watermark, or a changed
    partition binding all falsify the scenario.
    """

    scenario = OperationalHistoryScenario.DUPLICATE_DELIVERY
    observation = full_observation(binding, SyntheticSlot.WARM)
    before_bound = await history.resolve_evidence_partitions((observation.observation_id,))
    if not before_bound:
        return _unobserved(scenario, "duplicate_candidate_unavailable")
    before = await journal.append_change_batch(())
    replayed = await journal.append_change_batch((observation,))
    after = await journal.append_change_batch(())
    after_bound = await history.resolve_evidence_partitions((observation.observation_id,))
    owned = {item.partition_id for item in partitions}
    inserted = int(getattr(replayed, "inserted", 1))
    watermark_delta = int(getattr(after, "high_watermark", -1)) - int(
        getattr(before, "high_watermark", 0)
    )
    key = binding.idempotency_key(scenario, target=observation.observation_id)
    return ScenarioObservation(
        scenario=scenario,
        checks=(
            scenario_check("duplicate_suppressed", inserted == 0),
            scenario_check("journal_watermark_unchanged", watermark_delta == 0),
            scenario_check(
                "state_unchanged_on_replay",
                after_bound == before_bound and set(after_bound).issubset(owned),
            ),
            scenario_check(
                "idempotency_key_stable",
                key == binding.idempotency_key(scenario, target=observation.observation_id),
            ),
        ),
        evidence_digests=(
            evidence_digest(
                {
                    "observation": observation.observation_id,
                    "inserted": inserted,
                    "watermark_delta": watermark_delta,
                    "partitions": list(after_bound),
                }
            ),
        ),
    )


async def observe_late_observation(
    *,
    binding: CampaignBinding,
    now: datetime,
    history: LifecycleHistoryStore,
    partitions: Sequence[ObservationPartition],
) -> ScenarioObservation:
    """Prove a real correction binding exists and close it inside this scope only.

    The correction partition is the one the deployed lifecycle binder created for the
    out-of-order arrival, so its ``correction_of`` edge is real rather than declared.
    Closure runs through the scope-bounded correction closure, which advances no
    global projection watermark and touches no other scope, so the durable receipt
    never implies that a broad production projection completed.
    """

    scenario = OperationalHistoryScenario.LATE_OBSERVATION
    late = late_observation(binding)
    bound = await history.resolve_evidence_partitions((late.observation_id,))
    owned = {item.partition_id: item for item in partitions}
    if len(bound) != 1 or bound[0] not in owned:
        return _unobserved(scenario, "correction_binding_unavailable")
    correction = owned[bound[0]]
    created = (
        correction.kind is ObservationPartitionKind.CORRECTION
        and correction.correction_of is not None
        and correction.correction_of in owned
        and correction.scope_ref == binding.scope.scope_ref
    )
    try:
        await history.close_scope_corrections(
            scope_ref=binding.scope.scope_ref,
            generation=binding.campaign_id,
            projection_watermark=correction.last_watermark,
            closed_at=now,
        )
    except ValueError:
        _LOGGER.warning("scope correction closure has no persisted ontology manifest")
        return _unobserved(scenario, "correction_closure_unavailable")
    receipt = await history.latest_correction(correction.partition_id)
    if receipt is None:
        return _unobserved(scenario, "correction_receipt_unavailable")
    return ScenarioObservation(
        scenario=scenario,
        checks=(
            scenario_check("correction_partition_created", created),
            scenario_check(
                "correction_replay_complete",
                receipt.complete and receipt.correction_partition_id == correction.partition_id,
            ),
            scenario_check(
                "correction_closure_recorded",
                receipt.projection_watermark >= correction.last_watermark,
            ),
            scenario_check(
                "correction_scope_bounded",
                correction.scope_ref == binding.scope.scope_ref,
            ),
        ),
        evidence_digests=tuple(
            sorted(
                {
                    receipt.digest,
                    evidence_digest(
                        {
                            "correction": correction.partition_id,
                            "corrects": correction.correction_of,
                            "observation": late.observation_id,
                        }
                    ),
                }
            )
        ),
    )


async def observe_delete_recreate(
    *,
    binding: CampaignBinding,
    history: LifecycleHistoryStore,
) -> ScenarioObservation:
    """Verify the persisted closed and open incarnations the real lifecycle produced.

    The upsert, confirmed tombstone, and upsert arrivals were appended by the fixture
    through the deployed journal, so the incarnation rows this probe reads were opened
    and closed by the lifecycle binder itself. Nothing here writes an incarnation.
    """

    scenario = OperationalHistoryScenario.DELETE_RECREATE
    opened, tombstoned, reopened = incarnation_lifecycle(binding)
    resource_ref = synthetic_resource_ref(binding, SyntheticSlot.INCARNATION)
    incarnations = await history.list_incarnations(resource_ref)
    if len(incarnations) < 2:
        return _unobserved(scenario, "incarnation_history_unavailable")
    closed = [item for item in incarnations if item.closed_at is not None]
    live = [item for item in incarnations if item.closed_at is None]
    prior = closed[0] if closed else None
    current = live[0] if live else None
    disjoint: bool | None = None
    if prior is not None and current is not None and prior.closed_at is not None:
        disjoint = (
            prior.closed_at <= current.opened_at and prior.incarnation_id != current.incarnation_id
        )
    return ScenarioObservation(
        scenario=scenario,
        checks=(
            scenario_check(
                "prior_incarnation_recorded",
                prior is not None
                and prior.opening_observation_id == opened.observation_id
                and prior.closing_observation_id == tombstoned.observation_id,
            ),
            scenario_check(
                "new_incarnation_distinct",
                current is not None
                and current.opening_observation_id == reopened.observation_id
                and (prior is None or current.incarnation_id != prior.incarnation_id),
            ),
            scenario_check("incarnation_history_disjoint", disjoint),
            scenario_check(
                "tombstone_close_effective",
                prior is not None and prior.closed_at == tombstoned.effective_at,
            ),
        ),
        evidence_digests=tuple(sorted({item.digest for item in incarnations})),
    )


async def observe_schema_replay(
    *,
    binding: CampaignBinding,
    records: LifecycleRecordReader,
    partitions: Sequence[ObservationPartition],
    archived: Sequence[Mapping[str, Any]],
) -> ScenarioObservation:
    """Replay one record at both releases through the canonical schema replay.

    Both arms use :func:`replay_inventory_observation_schema`, the replay the provider
    contract exports, on records that actually exist: the N record is read from the
    journal rows bound to a synthetic partition, and the N-1 record is read back out of
    the archived artifact. The two arms are matched on one observation identity, so
    cross-release stability compares a record with its own earlier form rather than
    with an unrelated record. No ontology release label is invented for either arm.
    """

    scenario = OperationalHistoryScenario.SCHEMA_REPLAY
    persisted: list[Mapping[str, Any]] = []
    for partition in partitions:
        persisted.extend(
            dict(item) for item in await records.archive_records(partition.partition_id)
        )
    prior = prior_schema_record(archived)
    if prior is None or current_schema_record(persisted) is None:
        return _unobserved(scenario, "schema_record_unavailable")
    identity = prior.get("observation_id")
    current = next(
        (item for item in persisted if item.get("observation_id") == identity),
        None,
    )
    if current is None:
        return _unobserved(scenario, "schema_counterpart_unavailable")
    current_replay = replay_inventory_observation_schema(current)
    prior_replay = replay_inventory_observation_schema(prior)
    foreign = any(
        item.get("schema_version") != INVENTORY_OBSERVATION_SCHEMA_VERSION for item in persisted
    ) or any(item.get("schema_version") != PRIOR_SCHEMA_VERSION for item in archived)
    stable = cross_release_stable_body(
        prior_replay.transformed_record
    ) == cross_release_stable_body(current)
    return ScenarioObservation(
        scenario=scenario,
        checks=(
            scenario_check(
                "current_release_replayed",
                current_replay.source_schema_version == INVENTORY_OBSERVATION_SCHEMA_VERSION
                and current_replay.transformed_digest == current_replay.original_digest,
            ),
            scenario_check(
                "prior_release_replayed",
                prior_replay.source_schema_version == PRIOR_SCHEMA_VERSION
                and prior_replay.target_schema_version == INVENTORY_OBSERVATION_SCHEMA_VERSION
                and prior_replay.transformed_digest != prior_replay.original_digest,
            ),
            scenario_check("archived_prior_record_present", True),
            scenario_check("no_foreign_release_observed", not foreign),
            scenario_check("cross_release_graph_stable", stable),
        ),
        evidence_digests=tuple(
            sorted(
                {
                    evidence_digest({"current": current_replay.transformed_digest}),
                    evidence_digest({"prior": prior_replay.transformed_digest}),
                }
            )
        ),
    )


__all__ = [
    "LifecycleHistoryStore",
    "LifecycleRecordReader",
    "observe_delete_recreate",
    "observe_duplicate_delivery",
    "observe_late_observation",
    "observe_schema_replay",
]
