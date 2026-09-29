"""Auxiliary catalog identity, T2 quality gate, and control-loop collaborator assembly."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any, cast

from fdai.composition import Container, LlmBindings
from fdai.core.executor import (
    DirectApiExecutionPort,
    ShadowExecutor,
    ThorExecutionPort,
    ToolCallShadowExecutor,
)
from fdai.core.quality_gate import (
    DeterministicEvidenceKind,
    DeterministicEvidenceVerifier,
    HashedRuleEmbeddingIndex,
    QualityGate,
    QualityGateConfig,
    RagGroundingSource,
    RuleBasedVerifier,
    SelfConsistencySampler,
    UnavailableDeterministicEvidenceVerifier,
)
from fdai.core.quality_gate.promotion import (
    ActionModeSource,
    RubricModeResolver,
    RubricPromotionRegistry,
)
from fdai.core.quality_gate.self_consistency import SelfConsistencyCascade
from fdai.shared.contracts.models import Rule
from fdai.shared.providers.event_bus import EventBus


def _build_self_consistency_cascade(
    container: Container,
    llm_bindings: LlmBindings,
) -> SelfConsistencyCascade | None:
    """Return the configured T2 stability cascade, or ``None`` when disabled.

    Sampling costs one extra model call per sample, so it stays opt-in through
    ``llm.self_consistency_samples``. The primary cross-check model is the sampled
    proposer seam.
    """

    llm_config = container.config.llm
    if llm_config.self_consistency_samples < 1:
        return None
    return SelfConsistencyCascade(
        sampler=SelfConsistencySampler(
            proposer=llm_bindings.cross_check_models[0],
            samples=llm_config.self_consistency_samples,
        ),
        sample_threshold=llm_config.self_consistency_sample_threshold,
        stability_threshold=llm_config.self_consistency_stability_threshold,
    )


def _legacy_executor_bindings(
    port: ThorExecutionPort,
) -> tuple[
    ShadowExecutor,
    DirectApiExecutionPort | None,
    ToolCallShadowExecutor | None,
]:
    """Adapt the injected Thor port to the unchanged Core and HIL APIs."""
    return (
        cast(ShadowExecutor, port.pr_native),
        port.direct_api,
        cast(ToolCallShadowExecutor | None, port.tool_call),
    )


def _resolve_t2_deterministic_evidence_verifiers(
    container: Container,
) -> dict[DeterministicEvidenceKind, DeterministicEvidenceVerifier]:
    configured = container.t2_deterministic_evidence_verifiers or tuple(
        UnavailableDeterministicEvidenceVerifier(
            kind=kind,
            reason=f"{kind.value}_evidence_provider_unavailable",
        )
        for kind in DeterministicEvidenceKind
    )
    return {verifier.kind: verifier for verifier in configured}


def rca_catalog_revision(
    *,
    rules: Sequence[Any],
    action_types: Sequence[Any],
    ontology_release_digest: str,
) -> str:
    """Return a deterministic identity for RCA catalog inputs."""

    payload = {
        "action_types": [
            item.model_dump(mode="json", exclude_none=True)
            for item in sorted(action_types, key=lambda value: value.name)
        ],
        "ontology_release_digest": ontology_release_digest,
        "rules": [
            item.model_dump(mode="json", exclude_none=True)
            for item in sorted(rules, key=lambda value: value.id)
        ],
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def build_irp_event_handler(
    *,
    container: Container,
    bus: EventBus,
    runtime_settings: Any | None = None,
) -> Any | None:
    """Build the alert-to-investigation bridge when explicitly enabled."""

    from fdai.core.investigation import InvestigationCoordinator, default_analyzers
    from fdai.core.irp import IrpCoordinator
    from fdai.delivery.irp import (
        EventBusIrpProposalRouter,
        IrpEventHandler,
        RuntimeSettingsIrpEventHandler,
    )

    signal_writer = None
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if dsn:
        from fdai.delivery.persistence import (
            PostgresReportSignalStore,
            PostgresReportSignalStoreConfig,
        )

        signal_writer = PostgresReportSignalStore(config=PostgresReportSignalStoreConfig(dsn=dsn))

    def build_handler(budget_seconds: float) -> IrpEventHandler:
        coordinator = IrpCoordinator(
            investigator=InvestigationCoordinator(
                analyzers=default_analyzers(container.metric_provider)
            ),
            proposal_router=EventBusIrpProposalRouter(
                bus=bus,
                topic=container.config.kafka.topic_events,
            ),
            investigation_budget_seconds=budget_seconds,
        )
        return IrpEventHandler(coordinator=coordinator, signal_writer=signal_writer)

    if runtime_settings is not None:
        return RuntimeSettingsIrpEventHandler(
            settings=runtime_settings,
            handler_factory=build_handler,
        )
    if os.environ.get("FDAI_IRP_ENABLED", "").strip() != "1":
        return None
    budget_raw = os.environ.get("FDAI_IRP_BUDGET_SECONDS", "").strip()
    try:
        budget_seconds = float(budget_raw) if budget_raw else 60.0
    except ValueError as exc:
        raise RuntimeError("FDAI_IRP_BUDGET_SECONDS MUST be a number") from exc
    return build_handler(budget_seconds)


def build_rubric_mode_resolver(
    container: Container,
    action_modes: ActionModeSource,
) -> RubricModeResolver | None:
    """Return a receipt-driven rubric resolver only when the deployment binds its evidence.

    ``Container`` accepts the receipt source and verifier only as a pair. Binding them is the
    deployment's explicit opt-in: the rubric leg can then leave shadow for one ActionType only when
    that ActionType already enforces and a current, independently verified receipt binds the same
    revision and identity. Without the pair, no resolver exists and the leg stays in shadow.
    """
    source = container.rubric_promotion_receipt_source
    verifier = container.rubric_promotion_receipt_verifier
    if source is None or verifier is None:
        return None
    return RubricPromotionRegistry(
        action_modes=action_modes,
        receipt_verifier=verifier,
        receipt_source=source,
    )


def build_t2_quality_gate(
    container: Container,
    *,
    rules_by_id: Mapping[str, Rule],
    action_modes: ActionModeSource,
    deterministic_evidence_verifiers: (
        Mapping[DeterministicEvidenceKind, DeterministicEvidenceVerifier] | None
    ),
) -> QualityGate:
    """Build the production T2 gate from container bindings and the active rule set."""
    llm_bindings = container.require_llm_bindings()
    rubric_mode_resolver = build_rubric_mode_resolver(container, action_modes)
    return QualityGate(
        verifier=RuleBasedVerifier(rules_by_id=dict(rules_by_id)),
        cross_check_models=llm_bindings.cross_check_models,
        grounding=RagGroundingSource(
            rules=dict(rules_by_id),
            embedding_index=HashedRuleEmbeddingIndex(),
        ),
        rubric_evaluator=llm_bindings.rubric_evaluator,
        rubric_mode_resolver=rubric_mode_resolver,
        deterministic_evidence_verifiers=deterministic_evidence_verifiers,
        config=QualityGateConfig(
            confidence_threshold=container.config.llm.quality_gate_confidence_threshold,
            require_cross_check_quorum=container.config.llm.quality_gate_quorum,
            # The configured ceiling stays shadow unless the receipt evidence pair is bound.
            rubric_shadow=rubric_mode_resolver is None,
        ),
    )


__all__ = [
    "build_irp_event_handler",
    "build_rubric_mode_resolver",
    "build_t2_quality_gate",
    "rca_catalog_revision",
]
