"""Composition-root CLI for scheduled baseline and pattern-growth jobs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import httpx
import psycopg

from fdai.composition import (
    AzureWireOverrides,
    Container,
    default_container_from_env,
    wire_azure_container,
)
from fdai.core.assurance_twin import (
    EffectModelStatus,
    GraphDynamicClosureCoordinator,
    GraphDynamicClosureRunner,
    MetricGraphTrajectoryOutcomeSource,
    StateStoreEffectModelRegistry,
    StateStoreGraphEffectModelRegistry,
    StateStoreTrajectoryEpisodeLedger,
)
from fdai.core.assurance_twin.feedback_generation import REBUILD_PURPOSE, generation_scope
from fdai.core.measurement import (
    OperationalPromotionEvaluator,
    OperationalPromotionMeasurementRunner,
)
from fdai.core.measurement.cohort_claim_policy import (
    COHORT_CLAIM_POLICY_PATH,
    load_cohort_claim_policy,
)
from fdai.core.measurement.pattern_growth import TemporalHoldoutValidator
from fdai.core.measurement.regression import RegressionDetector
from fdai.core.measurement.runners import (
    AutomatedBaselineRunner,
    DynamicLearningRunner,
    PatternGrowthIntakeRunner,
)
from fdai.core.operator_memory import InMemoryOperatorMemoryStore
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.measurement.admitted_operational_promotion import (
    AdmittedOperationalPromotionEvidenceSource,
)
from fdai.delivery.measurement.cohort_inventory import (
    PostgresCohortEvidenceInventorySource,
)
from fdai.delivery.measurement.feedback_revision_source import PostgresFeedbackRevisionSource
from fdai.delivery.measurement.holdout import (
    HoldoutVerifiedPatternBuilder,
    StateStoreTemporalHoldoutEvidenceSource,
)
from fdai.delivery.measurement.measured_policy import (
    MeasuredPolicyRunner,
    MeasuredPolicyRunReport,
    StateStoreMeasuredPolicyBatchSource,
)
from fdai.delivery.measurement.operational_promotion_evidence import (
    ImmutableFileOperationalPromotionEvidenceSource,
    ManifestCausalPromotionReceiptVerifier,
    ManifestOperationalPromotionUnitVerifier,
    OperationalPromotionEvidenceManifest,
)
from fdai.delivery.measurement.outcome_assurance_producer import (
    OutcomeAssuranceProjectionProducer,
)
from fdai.delivery.measurement.pattern_evidence import (
    PatternEvidenceProducer,
    PostgresPatternEvidenceSource,
    PostgresPatternStatisticsWriter,
)
from fdai.delivery.measurement.postgres_growth import (
    PostgresResponseOutcomeSource,
    PostgresVerifiedOutcomeSource,
    PostgresVerifiedPatternBuilder,
)
from fdai.delivery.measurement.postgres_growth_writer import PostgresShadowPatternWriter
from fdai.delivery.measurement.scenario_replayer import (
    FROZEN_SCENARIO_ASSET_ROOT,
    FrozenScenarioReplayer,
)
from fdai.delivery.persistence import (
    PgVectorPatternLibraryConfig,
    PostgresStateStore,
    PostgresStateStoreConfig,
    StateStoreActionPromotionRegistry,
    StateStoreDecisionEvidenceAdmissionProvider,
    StateStoreOperationalPromotionReceiptStore,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.configuration import _model_endpoint_resolver
from fdai.runtime.venue import ExecutionVenue, resolve_execution_venue, uses_developer_identity
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.delivery.measurement_runner_cli")


class MeasurementMode(StrEnum):
    BASELINE = "baseline"
    COHORT_INVENTORY = "cohort-inventory"
    GROWTH = "growth"
    DYNAMIC_LEARNING = "dynamic-learning"
    DYNAMIC_REBUILD = "dynamic-rebuild"
    PATTERN_GROWTH = "pattern-growth"
    GRAPH_DYNAMIC = "graph-dynamic"
    OPERATIONAL_PROMOTION = "operational-promotion"
    OUTCOME_ASSURANCE = "outcome-assurance"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} MUST be configured")
    return value


def _repo_root() -> Path:
    for candidate in (Path.cwd(), Path("/app"), *Path(__file__).resolve().parents):
        if (candidate / "rule-catalog").is_dir() and (
            candidate / FROZEN_SCENARIO_ASSET_ROOT
        ).is_dir():
            return candidate
    raise FileNotFoundError("measurement artifacts are missing from the runtime image")


def _catalog_root() -> Path:
    for candidate in (Path.cwd(), Path("/app"), *Path(__file__).resolve().parents):
        catalog = candidate / "rule-catalog"
        if catalog.is_dir():
            return catalog
    raise FileNotFoundError("rule catalog is missing from the runtime image")


async def _run_baseline() -> int:
    dsn = _required_env("FDAI_STATE_STORE_DSN")
    version = _required_env("FDAI_SCENARIO_SET_VERSION")
    audit_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    registry = StateStoreActionPromotionRegistry(store=audit_store)
    report = await AutomatedBaselineRunner(
        replayer=FrozenScenarioReplayer(
            repo_root=_repo_root(),
            scenario_set_version=version,
            audit_store=audit_store,
            promotion_registry=registry,
        ),
        detector=RegressionDetector(),
        registry=registry,
        audit_store=audit_store,
        persist_mode=registry.persist,
    ).run_once()
    policy_report = await _run_measured_policy(audit_store)
    _LOGGER.info(
        "measurement_baseline_complete aborted_reason=%s",
        report.aborted_reason or "none",
        extra={
            "scenario_set_version": report.scenario_set_version,
            "sample_count": report.sample_count,
            "regression_count": len(report.regressions),
            "demoted_action_types": list(report.demoted_action_types),
            "aborted": report.aborted_reason is not None,
            "policy_processed_count": policy_report.processed_count,
            "policy_rejected_count": policy_report.rejected_count,
            "policy_duplicate_count": policy_report.duplicate_count,
            "policy_rollback_count": policy_report.rollback_count,
        },
    )
    return 3 if report.aborted_reason is not None else 0


async def _run_cohort_inventory() -> int:
    dsn = _required_env("FDAI_STATE_STORE_DSN")
    revision = _required_env("FDAI_COHORT_REVISION")
    policy = load_cohort_claim_policy(_repo_root() / COHORT_CLAIM_POLICY_PATH)
    inventory = await PostgresCohortEvidenceInventorySource(
        dsn=dsn,
        policy=policy,
        expected_revision=revision,
    ).inventory(evaluated_at=datetime.now(tz=UTC))
    _LOGGER.info(
        "measurement_cohort_inventory_complete %s",
        json.dumps(inventory.to_log_record(), separators=(",", ":"), sort_keys=True),
    )
    return 0 if inventory.ready else 3


async def _run_measured_policy(
    audit_store: StateStore,
) -> MeasuredPolicyRunReport:
    return await MeasuredPolicyRunner(
        source=StateStoreMeasuredPolicyBatchSource(audit_store),
        store=audit_store,
    ).run_once()


@asynccontextmanager
async def _azure_learning_container() -> AsyncIterator[Container]:
    container = default_container_from_env()
    if container.config.llm.mode != "azure":
        raise RuntimeError("growth measurement requires llm.mode='azure' for 384-dim embeddings")
    endpoint = _required_env("FDAI_LLM_ENDPOINT")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=60.0, write=15.0, pool=5.0)
    ) as client:
        identity: WorkloadIdentity = (
            AsyncAzureCliWorkloadIdentity.from_env()
            if uses_developer_identity(resolve_execution_venue())
            else ManagedIdentityWorkloadIdentity(http_client=client)
        )
        container = await wire_azure_container(
            container,
            http_client=client,
            identity=identity,
            overrides=AzureWireOverrides(
                endpoint=endpoint,
                model_endpoint_resolver=_model_endpoint_resolver(
                    endpoint, os.environ.get("FDAI_MODEL_ENDPOINTS_JSON")
                ),
                catalog_root=_repo_root() / "rule-catalog",
                operator_memory_store=InMemoryOperatorMemoryStore(),
            ),
        )
        yield container


async def _run_dynamic_learning() -> int:
    """Scalar learning needs only the durable source and challenger registry."""
    dsn = _required_env("FDAI_STATE_STORE_DSN")
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    report = await DynamicLearningRunner(
        outcome_source=PostgresResponseOutcomeSource(dsn=dsn, state_store=store),
        registry=StateStoreEffectModelRegistry(
            store,
            feedback_source=PostgresFeedbackRevisionSource(dsn=dsn),
        ),
        audit_store=store,
    ).run_once()
    _LOGGER.info(
        "measurement_dynamic_learning_complete",
        extra={
            "total_outcomes": report.total_outcomes,
            "accepted_count": report.accepted_count,
            "rejected_count": report.rejected_count,
        },
    )
    return 0


async def _run_dynamic_rebuild() -> int:
    if resolve_execution_venue(os.environ) is ExecutionVenue.DEPLOYED:
        _LOGGER.error(
            "dynamic_rebuild_unavailable",
            extra={"reason": "deployment_admission_binding_required"},
        )
        return 3
    dsn = _required_env("FDAI_STATE_STORE_DSN")
    action_type = _required_env("FDAI_EFFECT_REBUILD_ACTION_TYPE")
    metric = _required_env("FDAI_EFFECT_REBUILD_METRIC")
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    source = PostgresFeedbackRevisionSource(dsn=dsn)
    registry = StateStoreEffectModelRegistry(store, feedback_source=source)
    registration = await registry.inspect_registration(
        status=EffectModelStatus.CHALLENGER,
        action_type_id=action_type,
        metric=metric,
    )
    if registration is None:
        _LOGGER.error(
            "dynamic_rebuild_unavailable", extra={"reason": "registered_seed_unavailable"}
        )
        return 3
    current, seed = registration
    if seed is None:
        _LOGGER.error(
            "dynamic_rebuild_unavailable", extra={"reason": "registered_seed_unavailable"}
        )
        return 3
    outcomes = await source.outcomes_for_scope(action_type_id=action_type, metric=metric)
    if not outcomes:
        _LOGGER.error("dynamic_rebuild_unavailable", extra={"reason": "outcomes_unavailable"})
        return 3
    as_of = max(seed.learned_through, *(item.recorded_at for item in outcomes))
    candidate = await registry.preview_rebuild(seed=seed, outcomes=outcomes, as_of=as_of)
    if candidate is None:
        _LOGGER.error("dynamic_rebuild_unavailable", extra={"reason": "registered_seed_changed"})
        return 3
    admission = await StateStoreDecisionEvidenceAdmissionProvider(store=store).admit(
        evidence_digest="sha256:" + candidate.input_manifest_digest,
        scope_digest=generation_scope(action_type, metric),
        purpose_id=REBUILD_PURPOSE,
        source_revision=candidate.input_manifest_digest,
    )
    if admission is None:
        print(
            json.dumps(
                {
                    "status": "review_required",
                    "input_manifest_digest": candidate.input_manifest_digest,
                    "execution_authority": False,
                    "promotion_authority": False,
                },
                sort_keys=True,
            )
        )
        _LOGGER.warning(
            "dynamic_rebuild_review_required",
            extra={"input_manifest_digest": candidate.input_manifest_digest},
        )
        return 3
    result = await registry.rebuild_challenger(
        seed=seed,
        outcomes=outcomes,
        as_of=as_of,
        expected_revision=current.revision,
        admission=admission,
    )
    _LOGGER.info(
        "dynamic_rebuild_complete", extra={"accepted": result.accepted, "reason": result.reason}
    )
    return 0 if result.accepted or result.reason == "rebuild_already_applied" else 3


async def _run_pattern_growth() -> int:
    dsn = _required_env("FDAI_STATE_STORE_DSN")
    pattern_dsn = os.environ.get("FDAI_T1_PATTERN_LIBRARY_DSN", "").strip() or dsn
    async with _azure_learning_container() as container:
        embedding_model = container.require_llm_bindings().embedding_model
        if embedding_model.dim != 384:
            raise RuntimeError(f"growth embedding dimension MUST be 384; got {embedding_model.dim}")
        state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
        evidence = PatternEvidenceProducer(
            source=PostgresPatternEvidenceSource(dsn=dsn),
            state_store=state_store,
            statistics_writer=PostgresPatternStatisticsWriter(
                config=PgVectorPatternLibraryConfig(dsn=pattern_dsn)
            ),
        )
        holdout_report = await evidence.publish_holdout_evidence()
        report = await PatternGrowthIntakeRunner(
            outcome_source=PostgresVerifiedOutcomeSource(
                dsn=dsn,
                state_store=state_store,
            ),
            pattern_builder=HoldoutVerifiedPatternBuilder(
                delegate=PostgresVerifiedPatternBuilder(
                    dsn=dsn,
                    embedding_model=embedding_model,
                ),
                evidence_source=StateStoreTemporalHoldoutEvidenceSource(state_store),
                validator=TemporalHoldoutValidator(),
                audit_store=state_store,
            ),
            writer=PostgresShadowPatternWriter(
                config=PgVectorPatternLibraryConfig(dsn=pattern_dsn)
            ),
            audit_store=state_store,
        ).run_once()
    statistics_report = await evidence.apply_measured_statistics()
    _LOGGER.info(
        "measurement_pattern_evidence",
        extra={
            "outcomes": holdout_report.outcomes,
            "envelopes_written": holdout_report.envelopes_written,
            "complete_envelopes": holdout_report.complete_envelopes,
            "patterns_updated": statistics_report.patterns_updated,
        },
    )
    _LOGGER.info(
        "measurement_pattern_growth_complete",
        extra={
            "total_outcomes": report.total_outcomes,
            "accepted_count": report.accepted_count,
            "rejected_count": report.rejected_count,
            "build_failures": report.build_failures,
            "deferred_count": report.deferred_count,
            "expired_count": report.expired_count,
        },
    )
    return 0


async def _run_graph_dynamic() -> int:
    dsn = _required_env("FDAI_STATE_STORE_DSN")
    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    async with _azure_learning_container() as container:
        trajectory_ledger = StateStoreTrajectoryEpisodeLedger(state_store)
        graph_registry = StateStoreGraphEffectModelRegistry(state_store)
        graph_reports = await GraphDynamicClosureRunner(
            outcome_source=MetricGraphTrajectoryOutcomeSource(
                ledger=trajectory_ledger,
                metrics=container.metric_provider,
            ),
            coordinator=GraphDynamicClosureCoordinator(
                ledger=trajectory_ledger,
                registry=graph_registry,
                audit_store=state_store,
            ),
            audit_store=state_store,
        ).run_once()
    _LOGGER.info(
        "measurement_graph_dynamic_complete",
        extra={
            "graph_dynamic_outcome_count": len(graph_reports),
            "graph_dynamic_update_count": sum(item.update_count for item in graph_reports),
        },
    )
    return 0


async def _run_growth() -> int:
    """Compatibility entrypoint; scalar receipts survive later pattern failures."""
    failed = False
    for name, consumer in (
        ("dynamic-learning", _run_dynamic_learning),
        ("pattern-growth", _run_pattern_growth),
        ("graph-dynamic", _run_graph_dynamic),
    ):
        try:
            result = await consumer()
        except (
            RuntimeError,
            ValueError,
            TimeoutError,
            PermissionError,
            httpx.HTTPError,
            psycopg.Error,
        ) as exc:
            failed = True
            _LOGGER.error(
                "measurement_consumer_failed",
                extra={"consumer": name, "error_type": type(exc).__name__},
            )
        else:
            if type(result) is not int or result != 0:
                failed = True
                _LOGGER.error("measurement_consumer_incomplete", extra={"consumer": name})
    return 3 if failed else 0


async def _run_operational_promotion() -> int:
    dsn = _required_env("FDAI_STATE_STORE_DSN")
    revision = _required_env("FDAI_REVISION")
    scenario_set_version = _required_env("FDAI_SCENARIO_SET_VERSION")
    evidence_root_raw = os.environ.get("FDAI_OPERATIONAL_PROMOTION_EVIDENCE_ROOT", "").strip()
    catalog_root = _catalog_root()
    evidence_root = Path(evidence_root_raw) if evidence_root_raw else catalog_root.parent
    evidence_root = evidence_root.resolve(strict=True)
    manifest_path = _bounded_evidence_path(
        root=evidence_root,
        value=_required_env("FDAI_OPERATIONAL_PROMOTION_MANIFEST"),
    )
    manifest = OperationalPromotionEvidenceManifest.load(manifest_path)
    action_types = load_ontology_catalog(
        catalog_root,
        schema_registry=PackageResourceSchemaRegistry(),
    ).action_types
    selected = tuple(
        action_type
        for action_type in action_types
        if action_type.name in manifest.action_type_names
    )
    missing = manifest.action_type_names - {action_type.name for action_type in selected}
    if missing:
        raise ValueError(
            "operational promotion manifest references unknown ActionTypes: "
            + ", ".join(sorted(missing))
        )
    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    evaluator = OperationalPromotionEvaluator(
        expected_fdai_revision=revision,
        expected_scenario_set_version=scenario_set_version,
        causal_receipt_verifier=ManifestCausalPromotionReceiptVerifier(manifest),
        unit_verifier=ManifestOperationalPromotionUnitVerifier(manifest),
    )
    results = await OperationalPromotionMeasurementRunner(
        source=AdmittedOperationalPromotionEvidenceSource(
            source=ImmutableFileOperationalPromotionEvidenceSource(manifest),
            admission_provider=StateStoreDecisionEvidenceAdmissionProvider(store=state_store),
        ),
        evaluator=evaluator,
        audit_store=state_store,
        receipt_sink=StateStoreOperationalPromotionReceiptStore(state_store),
        fdai_revision=revision,
        scenario_set_version=scenario_set_version,
    ).run(selected)
    aborted = tuple(item for item in results if item.aborted_reason is not None)
    _LOGGER.info(
        "operational_promotion_measurement_complete",
        extra={
            "scenario_set_version": scenario_set_version,
            "action_type_count": len(results),
            "ready_count": sum(item.receipt is not None and item.receipt.ready for item in results),
            "held_count": sum(
                item.receipt is not None and not item.receipt.ready for item in results
            ),
            "aborted_count": len(aborted),
        },
    )
    return 3 if aborted else 0


async def _run_outcome_assurance() -> int:
    import fdai_service_contracts as sc

    from fdai.core.measurement.outcome_assurance import (
        FinalizedOutcomeEvent,
        OutcomeMeasurementObservation,
    )

    dsn = _required_env("FDAI_STATE_STORE_DSN")
    principal_id = _required_env("FDAI_OUTCOME_ASSURANCE_PRINCIPAL_ID")
    root_raw = os.environ.get("FDAI_OUTCOME_ASSURANCE_ROOT", "").strip()
    root = Path(root_raw).resolve(strict=True) if root_raw else _catalog_root().parent
    bundle_path = _bounded_evidence_path(
        root=root,
        value=_required_env("FDAI_OUTCOME_ASSURANCE_SOURCE_BUNDLE_PATH"),
    )
    raw = json.loads(bundle_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "state" in raw or "alignment" in raw:
        raise ValueError(
            "Outcome Assurance source bundle MUST supply raw sources, "
            "not precomputed state/alignment"
        )
    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    receipt = await OutcomeAssuranceProjectionProducer(
        store=state_store
    ).publish_from_authoritative_sources(
        principal_id=principal_id,
        scope=sc.OutcomeAssuranceScope.model_validate(raw["scope"]),
        window=sc.OutcomeAssuranceWindow.model_validate(raw["window"]),
        sources=tuple(
            sc.OutcomeAssuranceSource.model_validate(item) for item in raw.get("sources", ())
        ),
        readiness=tuple(
            sc.OutcomeAssuranceReadiness.model_validate(item) for item in raw.get("readiness", ())
        ),
        finalized_events=tuple(
            FinalizedOutcomeEvent.model_validate(item) for item in raw.get("finalized_events", ())
        ),
        observations=tuple(
            OutcomeMeasurementObservation.model_validate(item)
            for item in raw.get("observations", ())
        ),
        outcomes=tuple(
            sc.OutcomeAssuranceMetric.model_validate(item) for item in raw.get("outcomes", ())
        ),
        guards=sc.OutcomeAssuranceControlSummary.model_validate(raw["guards"]),
        as_of=datetime.fromisoformat(str(raw["as_of"]).replace("Z", "+00:00")),
    )
    _LOGGER.info(
        "outcome_assurance_projection_published",
        extra=receipt.to_mapping(),
    )
    return 0 if receipt.state is sc.OutcomeAssuranceReadState.COMPLETE else 3


def _bounded_evidence_path(*, root: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("operational promotion evidence path escapes its configured root") from exc
    return resolved


async def _amain(argv: list[str]) -> int:
    mode_raw = argv[0].lower() if argv else os.environ.get("FDAI_MEASUREMENT_MODE", "").lower()
    try:
        mode = MeasurementMode(mode_raw)
    except ValueError:
        _LOGGER.error("invalid_measurement_mode", extra={"mode": mode_raw or "<unset>"})
        return 2
    try:
        async with asyncio.timeout(900):
            return await _run_mode(mode)
    except Exception:
        _LOGGER.exception("measurement_runner_failed", extra={"mode": mode.value})
        return 3


async def _run_mode(mode: MeasurementMode) -> int:
    if mode is MeasurementMode.BASELINE:
        return await _run_baseline()
    if mode is MeasurementMode.COHORT_INVENTORY:
        return await _run_cohort_inventory()
    if mode is MeasurementMode.GROWTH:
        return await _run_growth()
    if mode is MeasurementMode.DYNAMIC_LEARNING:
        return await _run_dynamic_learning()
    if mode is MeasurementMode.DYNAMIC_REBUILD:
        return await _run_dynamic_rebuild()
    if mode is MeasurementMode.PATTERN_GROWTH:
        return await _run_pattern_growth()
    if mode is MeasurementMode.GRAPH_DYNAMIC:
        return await _run_graph_dynamic()
    if mode is MeasurementMode.OUTCOME_ASSURANCE:
        return await _run_outcome_assurance()
    return await _run_operational_promotion()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("FDAI_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(_amain(list(argv) if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
