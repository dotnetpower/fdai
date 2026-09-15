"""Alert execution identities, evidence records, and injected publication contracts.

These definitions perform no dispatch and import no workflow coordinator. The public
execution facade re-exports them for existing callers.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.alert_noise import Ref, digest_record
from fdai_service_contracts.alert_noise_base import AlertContractBase, AlertTime, FalseOnly
from fdai_service_contracts.alert_noise_plan import (
    AlertApproval,
    AlertChangePlan,
    AlertDispatchEvidence,
    AlertRollbackBaseline,
)
from fdai_service_contracts.executor_models import Digest
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.safeguard_evidence_lifecycle import DispatchPort
from fdai.core.executor.safeguard_lifecycle_coordinator import SafeguardCoordinatedDispatchResult
from fdai.shared.contracts.models import Action, Rule
from fdai.shared.providers.remediation_pr import PublishReceipt, RemediationPr

RESTORE_ACTION = "ops.restore-alert-configuration"
ALERT_ACTIONS = frozenset(
    {
        "ops.update-alert-routing",
        "ops.set-alert-notification-window",
        "ops.tune-alert-evaluation",
        RESTORE_ACTION,
    }
)
AlertPublicationCheck = Callable[[datetime], None]


class AlertExecutionHeld(ValueError):  # noqa: N818 - preserve the public exception name
    """Content-free admission refusal; never include provider payloads in its reason."""


def alert_execution_key(action_type: str, plan_digest: str) -> str:
    """Bind retries to one plan and direction, independent of Process delivery attempts."""
    if (
        action_type not in ALERT_ACTIONS
        or re.fullmatch(r"sha256:[a-f0-9]{64}", plan_digest) is None
    ):
        raise AlertExecutionHeld("execution_identity_invalid")
    return f"alert-noise:{action_type}:{plan_digest}"


def alert_publication_digest(plan: AlertChangePlan, pr: RemediationPr) -> str:
    """Approval dry-run identity covers exact bytes, file, direction and before revision."""
    return content_digest(
        {
            "domain": "alert-noise-manual-pr-v1",
            "plan_digest": digest_record(plan),
            "action_type": pr.metadata.get("action_type"),
            "path": pr.patch_path,
            "source_digest": pr.metadata.get("source_digest"),
            "result_digest": pr.metadata.get("result_digest"),
            "patch_digest": "sha256:" + hashlib.sha256(pr.patch.encode("utf-8")).hexdigest(),
        }
    )


class AlertPlanReader(Protocol):
    """Resolve content-addressed plans and their exact historical rollback baseline."""

    async def read(self, plan_digest: str) -> AlertChangePlan: ...
    async def baseline(self, plan: AlertChangePlan) -> AlertRollbackBaseline: ...


class AlertRecoveryAdmission(AlertContractBase):
    """Separately verified current recovery receipt, not a renewed forward approval."""

    action_digest: Digest
    plan_digest: Digest
    rollback_ref: Digest
    dry_run_digest: Digest
    executor_ref: Ref
    receipt_ref: Ref
    evaluated_at: AlertTime
    valid_until: AlertTime
    authorization_until: AlertTime
    synthetic: FalseOnly = False


class AlertRecoveryAuthorityReader(Protocol):
    """Resolve independent recovery authority including its current revocation state."""

    async def admission(
        self,
        *,
        action: Action,
        plan: AlertChangePlan,
    ) -> AlertRecoveryAdmission | None: ...


class AlertAuthorityLease(Protocol):
    """Verify owner-issued proofs, not booleans or an asserted executor name.

    Revalidate exact ActionType/catalog and workflow lineage, authenticated executor,
    all tenant/service/dependency scopes and roles, current risk/promotion, tested baseline,
    evaluation receipt, exact approved patch and repository source revision. Resolve every
    proof reference and enforce writer exclusivity for all plan.lock_refs through publication.
    Recovery verifies its own quorum/envelope and hold release, never forward consent.
    Missing, synthetic, revoked or expired proof MUST raise, including at the final boundary.
    Authority/revocation revisions must remain fenced across the coordinator's final await;
    a cached role flag or an advisory writer lock is not an implementation of this lease.
    """

    async def require_current(
        self,
        *,
        action: Action,
        plan: AlertChangePlan,
        pr: RemediationPr,
        evidence: AlertDispatchEvidence | AlertRecoveryAdmission,
        approvals: tuple[AlertApproval, ...],
        now: datetime,
    ) -> None: ...

    def require_active(self, *, now: datetime) -> None:
        """Synchronously prove that verified authority and writer leases remain active."""
        ...


class AlertAuthorityFence(Protocol):
    """Acquire the governed writer fence, covering targets AND shared dependencies.

    This is not a process-local lock substitute. Composition must bind an authoritative
    exclusive-writer/conditional-source mechanism; no permissive implementation is shipped.
    """

    def hold(
        self,
        *,
        action: Action,
        plan: AlertChangePlan,
        pr: RemediationPr,
    ) -> AbstractAsyncContextManager[AlertAuthorityLease]: ...


class AlertPrDispatch(DispatchPort, Protocol):
    """One sink invocation's observations; the shared coordinator owns durable state."""

    receipt: PublishReceipt | None
    error: BaseException | None
    invoked: bool
    bundle_digest: str | None


class AlertPrDelivery(Protocol):
    """Prepare immutable content and place the real lifecycle guard at the publisher."""

    async def prepare(
        self,
        *,
        action: Action,
        rule: Rule,
        plan: AlertChangePlan,
    ) -> RemediationPr: ...
    def dispatch_port(
        self,
        *,
        pr: RemediationPr,
        revalidate: Callable[[], Awaitable[AlertPublicationCheck]],
        audit_intent: Callable[[str], Awaitable[None]],
        dry_run_receipt: str,
    ) -> AlertPrDispatch: ...


class AlertPublicationRecorder(Protocol):
    """Retain actual completed publication evidence for independent observation/restart."""

    async def record(
        self,
        *,
        action: Action,
        plan: AlertChangePlan,
        receipt: PublishReceipt,
        result: SafeguardCoordinatedDispatchResult,
    ) -> None: ...
