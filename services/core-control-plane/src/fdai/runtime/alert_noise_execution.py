"""Compose the alert manual-PR port around the existing Thor PR executor.

Composition grants no authority and creates no publisher, identity, lock or
safeguard coordinator. Only an existing GitOps publisher and a production-eligible
PostgreSQL evidenced lock can bind a writer fence. Its independent exclusion,
approval, promotion, source and recovery proofs must still exist at dispatch.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import MappingProxyType

from fdai_service_contracts.alert_noise import NoisePolicy
from fdai_service_contracts.alert_noise_plan import (
    AlertApproval,
    AlertChangePlan,
    AlertDispatchEvidence,
)

from fdai.core.detection.alert_noise.execution import (
    AlertActionExecution,
    AlertAuthorityLease,
    AlertExecutionHeld,
    AlertRecoveryAdmission,
)
from fdai.core.executor.port import _PrNativeExecutionPort
from fdai.core.executor.safeguard_lifecycle_coordinator import SafeguardLifecycleCoordinator
from fdai.core.risk_gate import ActionPromotionRegistry
from fdai.delivery.alert_noise_artifacts import AlertPlanArtifactPreparer, parse_alert_iac_bindings
from fdai.delivery.alert_noise_authority import (
    StateStoreAlertAuthorityReader,
    StateStoreAlertRecoveryAuthorityReader,
)
from fdai.delivery.alert_noise_evidence import StateStoreAlertEvaluationReader
from fdai.delivery.alert_noise_execution_records import StateStoreAlertPublicationRecorder
from fdai.delivery.alert_noise_fence import AlertLockTrust, StateStoreAlertAuthorityFence
from fdai.delivery.alert_noise_pr import (
    AlertManualPrDispatcher,
    StateStoreAlertPatchReader,
    StateStoreAlertPlanReader,
)
from fdai.delivery.gitops_pr.adapter import GitOpsPrAdapter
from fdai.delivery.persistence.postgres_resource_lock import (
    _PROVIDER_ID,
    _PROVIDER_VERSION,
    _VERIFIER_ID,
    PostgresAdvisoryResourceLock,
)
from fdai.delivery.persistence.state_store_action_promotion import StateStoreActionPromotionRegistry
from fdai.runtime.alert_noise_config import parse_alert_noise_config
from fdai.runtime.alert_noise_control import registered_alert_actions
from fdai.shared.contracts.models import Action, OntologyRelease
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.process_runtime import ProcessRuntimeStore
from fdai.shared.providers.remediation_pr import RemediationPr, RemediationPrPublisher
from fdai.shared.providers.resource_lock import (
    EvidenceResourceLock,
    ResourceLock,
    require_evidence_resource_lock,
)
from fdai.shared.providers.state_store import StateStore


class GitOpsAlertIaCSourceReader:
    """Read through the same real GitOps instance, retaining its credential/repository boundary.

    Reading an existing file is deferred until dispatch; construction never calls
    GitHub. The publisher's public read_existing API owns provider I/O and decoding.
    Writer exclusion, not this reader, must pin its source through publication.
    """

    def __init__(self, publisher: GitOpsPrAdapter) -> None:
        self._publisher = publisher

    async def read(self, *, path: str) -> str | None:
        """Read only the requested existing path; no fallback path or content is supplied."""
        return await self._publisher.read_existing(path)


def _for_scope[Binding](bindings: Mapping[str, Binding], plan: AlertChangePlan) -> Binding:
    binding = bindings.get(plan.scope_ref)
    if binding is None:
        raise AlertExecutionHeld("alert_writer_scope_unbound")
    return binding


class _ScopedAlertAuthority:
    """Route to the exact scope reader, which independently checks the bound tenant."""

    def __init__(self, readers: Mapping[str, StateStoreAlertAuthorityReader]) -> None:
        self._readers = MappingProxyType(dict(readers))

    async def approvals(self, plan: AlertChangePlan) -> tuple[AlertApproval, ...]:
        return await _for_scope(self._readers, plan).approvals(plan)

    async def dispatch_evidence(self, plan: AlertChangePlan) -> AlertDispatchEvidence:
        return await _for_scope(self._readers, plan).dispatch_evidence(plan)


class _ScopedAlertRecoveryAuthority:
    """Route recovery to its own admitted record, never to forward approvals."""

    def __init__(self, readers: Mapping[str, StateStoreAlertRecoveryAuthorityReader]) -> None:
        self._readers = MappingProxyType(dict(readers))

    async def admission(
        self,
        *,
        action: Action,
        plan: AlertChangePlan,
    ) -> AlertRecoveryAdmission | None:
        return await _for_scope(self._readers, plan).admission(action=action, plan=plan)


class _ScopedAlertAuthorityFence:
    """Select the plan's existing writer fence without a cross-scope fallback."""

    def __init__(self, fences: Mapping[str, StateStoreAlertAuthorityFence]) -> None:
        self._fences = MappingProxyType(dict(fences))

    def hold(
        self,
        *,
        action: Action,
        plan: AlertChangePlan,
        pr: RemediationPr,
    ) -> AbstractAsyncContextManager[AlertAuthorityLease]:
        return _for_scope(self._fences, plan).hold(action=action, plan=plan, pr=pr)


def _postgres_lock_binding(
    resource_lock: ResourceLock | None,
) -> tuple[EvidenceResourceLock, AlertLockTrust] | None:
    """Pin actual PostgreSQL metadata; never adapt a local or legacy lock into proof."""
    if (
        not isinstance(resource_lock, PostgresAdvisoryResourceLock)
        or resource_lock.production_eligible is not True
    ):
        return None
    provider = require_evidence_resource_lock(resource_lock, production=True)
    # These are the provider's receipt identities and the selected instance's
    # real trust anchor. Do not substitute a default anchor or copy its DSN.
    trust = AlertLockTrust(
        provider_id=_PROVIDER_ID,
        provider_version=_PROVIDER_VERSION,
        verifier_id=_VERIFIER_ID,
        verifier_version=_PROVIDER_VERSION,
        trust_anchor_id=resource_lock._config.trust_anchor_id,
    )
    return provider, trust


def build_alert_pr_execution_port(
    *,
    fallback: _PrNativeExecutionPort,
    audit_store: StateStore,
    publisher: RemediationPrPublisher,
    resource_lock: ResourceLock | None,
    coordinator: SafeguardLifecycleCoordinator | None,
    promotion_registry: ActionPromotionRegistry,
    ontology_release: OntologyRelease,
    decision_evidence_provider: DecisionEvidenceAdmissionProvider | None,
    process_store: ProcessRuntimeStore | None = None,
    environment: Mapping[str, str] | None = None,
    policy: NoisePolicy | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AlertActionExecution:
    """Wrap alert actions only, preserving the exact non-alert fallback and lifecycle.

    Missing configuration/source/writers keeps alert enforcement held. A missing
    real publisher or eligible lock leaves the fence None, even if other writer
    bindings exist; a recording publisher can never become the alert live sink.
    Neither optional DE nor promotion is fabricated. The authority readers accept
    only the same durable registry instance, or explicit unavailability.
    """
    config = parse_alert_noise_config(os.environ if environment is None else environment)
    source = (
        GitOpsAlertIaCSourceReader(publisher) if isinstance(publisher, GitOpsPrAdapter) else None
    )
    delivery = AlertManualPrDispatcher(
        patches=StateStoreAlertPatchReader(store=audit_store),
        publisher=publisher,
        source_reader=source,
    )
    authorities: dict[str, StateStoreAlertAuthorityReader] = {}
    recoveries: dict[str, StateStoreAlertRecoveryAuthorityReader] = {}
    fences: dict[str, StateStoreAlertAuthorityFence] = {}
    if config is not None and config.source_revision is not None and config.writers:
        registry = (
            promotion_registry
            if isinstance(promotion_registry, StateStoreActionPromotionRegistry)
            else None
        )
        lock_binding = _postgres_lock_binding(resource_lock) if source is not None else None
        bound_policy = policy if policy is not None else NoisePolicy()
        for scope_ref, writer in config.writers.items():
            scope = config.scopes[scope_ref]
            authority = StateStoreAlertAuthorityReader(
                store=audit_store,
                admissions=decision_evidence_provider,
                promotion_registry=registry,
                principal_refs=writer.principal_refs,
                scope_ref=scope_ref,
                tenant_ref=scope.tenant_ref,
                source_revision=config.source_revision,
                clock=clock,
            )
            recovery = StateStoreAlertRecoveryAuthorityReader(
                store=audit_store,
                admissions=decision_evidence_provider,
                promotion_registry=registry,
                principal_refs=writer.principal_refs,
                scope_ref=scope_ref,
                tenant_ref=scope.tenant_ref,
                source_revision=config.source_revision,
                clock=clock,
            )
            authorities[scope_ref], recoveries[scope_ref] = authority, recovery
            if lock_binding is not None:
                lock, trust = lock_binding
                fences[scope_ref] = StateStoreAlertAuthorityFence(
                    store=audit_store,
                    admissions=decision_evidence_provider,
                    lock=lock,
                    lock_trust=trust,
                    verification_trust_anchor_id=writer.verification_trust_anchor_id,
                    authority=authority,
                    recovery=recovery,
                    policy=bound_policy,
                    scope_ref=scope_ref,
                    tenant_ref=scope.tenant_ref,
                    repository_ref=writer.repository_ref,
                    repository_revision=writer.repository_revision,
                    writer_ref=writer.executor_ref,
                    source_revision=config.source_revision,
                    clock=clock,
                    production=True,
                    evaluations=StateStoreAlertEvaluationReader(
                        store=audit_store,
                        admissions=decision_evidence_provider,
                        scope_ref=scope_ref,
                        tenant_ref=scope.tenant_ref,
                        source_revision=config.source_revision,
                        clock=clock,
                    ),
                )
    return AlertActionExecution(
        plans=StateStoreAlertPlanReader(store=audit_store),
        delivery=delivery,
        authority=_ScopedAlertAuthority(authorities) if authorities else None,
        fence=_ScopedAlertAuthorityFence(fences) if fences else None,
        recovery=_ScopedAlertRecoveryAuthority(recoveries) if recoveries else None,
        coordinator=coordinator,
        audit_store=audit_store,
        fallback=fallback,
        registered_actions=registered_alert_actions(ontology_release),
        clock=clock,
        publication_recorder=(
            StateStoreAlertPublicationRecorder(
                store=audit_store,
                processes=process_store,
                clock=clock,
            )
            if process_store is not None
            else None
        ),
    )


__all__ = ["GitOpsAlertIaCSourceReader", "build_alert_pr_execution_port"]


def build_alert_plan_artifacts(
    *,
    store: StateStore,
    publisher: RemediationPrPublisher,
    environment: Mapping[str, str] | None = None,
) -> AlertPlanArtifactPreparer | None:
    """Bind exact private source selectors to the already configured real IaC publisher."""
    values = os.environ if environment is None else environment
    bindings = parse_alert_iac_bindings(values)
    if not bindings:
        return None
    config = parse_alert_noise_config(values)
    if config is None or not isinstance(publisher, GitOpsPrAdapter):
        raise RuntimeError("alert IaC preparation requires scope and real repository bindings")
    return AlertPlanArtifactPreparer(
        store=store, source=GitOpsAlertIaCSourceReader(publisher), bindings=bindings
    )
