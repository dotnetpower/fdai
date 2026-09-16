"""Runtime composition of existing human-access sources, fixed owners and isolated transport.

No constructor performs provider I/O or obtains a token. Core retains only its
ordinary read identity; a configured mutation identity is never constructed here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

import httpx
from fdai_service_contracts.human_access import parse_human_access_role_groups

from fdai.core.control_loop import ControlLoop
from fdai.core.human_assignment.execution_approval import HumanAccessApprovalService
from fdai.core.human_assignment.execution_material import (
    HumanAccessMaterialBuilder,
    HumanAccessMaterialStore,
)
from fdai.core.human_assignment.execution_recovery import HumanAccessRecoverySource
from fdai.core.human_assignment.execution_sources import (
    HumanAccessCaseSource,
    HumanAccessCurrentPublisher,
)
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.rbac.roles import Role
from fdai.delivery.human_access_closure import HumanAccessClosureReconciler
from fdai.delivery.identity.entra_directory import EntraHumanIdentityDirectory
from fdai.delivery.identity.human_access_observer import IndependentHumanAccessObserver
from fdai.delivery.identity.scoped_duty_directory import EntraDutySubjectResolver
from fdai.delivery.identity.scoped_duty_owners import CurrentScopedDutyOwners
from fdai.delivery.persistence.state_store_action_promotion import StateStoreActionPromotionRegistry
from fdai.runtime.approval_policy import approver_authorizer_from_environment
from fdai.runtime.human_access_workflow import HumanAccessWorkflowRuntime
from fdai.runtime.safeguard_isolated_executor import SafeguardBoundEventBusDirectApiExecutionClient
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity


def build_human_access_workflow(
    *,
    loop: ControlLoop,
    store: StateStore,
    environment: Mapping[str, str],
    http_client: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None,
    enforce_ready: Callable[[], bool],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> HumanAccessWorkflowRuntime | None:
    """Bind only real current readers and an already safeguard-bound remote execution port."""
    raw = environment.get("FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON", "").strip()
    if (
        not raw
        or http_client is None
        or identity is None
        or not environment.get("FDAI_STATE_STORE_DSN")
    ):
        return None
    port = loop._direct_api_executor
    gate, table = loop._risk_gate, loop._risk_table
    if (
        not isinstance(port, SafeguardBoundEventBusDirectApiExecutionClient)
        or gate is None
        or table is None
    ):
        return None
    registry = gate._registry
    if not isinstance(registry, StateStoreActionPromotionRegistry):
        return None
    read_principal = environment.get("FDAI_MI_CLIENT_ID", "").strip().casefold()
    mutation_principal = environment.get("FDAI_HUMAN_ACCESS_MI_CLIENT_ID", "").strip().casefold()
    if read_principal and read_principal == mutation_principal:
        raise ValueError(
            "Core read identity MUST NOT share isolated human-access mutation identity"
        )
    if not read_principal:
        return None
    groups = {Role(role): group for role, group in parse_human_access_role_groups(raw).items()}
    subjects = EntraDutySubjectResolver(
        http_client, identity, None, clock, timedelta(minutes=5), 5.0
    )
    owners = CurrentScopedDutyOwners(
        subjects,
        EntraHumanIdentityDirectory(http_client, identity, max_attempts=1, roster_cache_seconds=0),
        {"Owner": next(group for role, group in groups.items() if role.value == "Owner")},
        clock,
        5.0,
    )
    cases = AssignmentCaseService(store)
    builder = HumanAccessMaterialBuilder(cases, HumanAccessMaterialStore(store), groups)
    recovery = HumanAccessRecoverySource(builder, port.coordinator.target_fences)
    source = HumanAccessCaseSource(cases, groups, registry, clock, recovery.check)
    approvals = HumanAccessApprovalService(
        store,
        owners,
        source.check,
        clock,
        approver_authorizer_from_environment(environment),
    )
    current = HumanAccessCurrentPublisher(source, approvals, clock)
    observer = IndependentHumanAccessObserver(
        http_client, identity, "core-read:" + read_principal, clock
    )
    return HumanAccessWorkflowRuntime(
        builder,
        approvals,
        current,
        loop._action_builder,
        gate,
        table,
        port,
        observer,
        enforce_ready,
        clock,
        HumanAccessClosureReconciler(
            port.coordinator.closure_store, store, clock, observer.identity_ref
        ),
        recovery,
        loop._kill_switch_refresher,
        lambda: (
            (loop._kill_switch is not None and loop._kill_switch.is_engaged())
            or (loop._degradation is not None and not loop._degradation.autonomy_permitted())
        ),
    )


__all__ = ["build_human_access_workflow"]
