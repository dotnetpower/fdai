"""Auxiliary catalog identity and control-loop collaborator assembly."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
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
    SelfConsistencySampler,
    UnavailableDeterministicEvidenceVerifier,
)
from fdai.core.quality_gate.self_consistency import SelfConsistencyCascade
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


__all__ = ["build_irp_event_handler", "rca_catalog_revision"]
