"""Retain exact alert authority models and describe dispatch bindings without granting rights."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Annotated

from fdai_service_contracts.alert_noise import Ref, digest_record
from fdai_service_contracts.alert_noise_base import AlertContractBase
from fdai_service_contracts.alert_noise_plan import (
    AlertApproval,
    AlertChangePlan,
    AlertDispatchEvidence,
)
from fdai_service_contracts.executor_models import Digest
from fdai_service_contracts.ontology_query import content_digest
from pydantic import Field

from fdai.core.detection.alert_noise.execution import (
    AlertRecoveryAdmission,
    alert_publication_digest,
)
from fdai.core.executor.safeguards import full_action_digest
from fdai.core.risk_gate.gate import ActionModeRecord
from fdai.delivery.alert_noise_evidence import AdmittedAlertRecord
from fdai.shared.contracts.models import Action
from fdai.shared.providers.remediation_pr import RemediationPr


class _ApprovalContext(AlertContractBase):
    plan_digest: Digest
    approvals: Annotated[tuple[AlertApproval, ...], Field(min_length=2, max_length=128)]
    process_id: Annotated[str, Field(min_length=1, max_length=512)]
    approval_step_id: Ref
    attempt: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]


class _ForwardRecord(_ApprovalContext):
    dispatch: AlertDispatchEvidence


class _RecoveryRecord(_ApprovalContext):
    admission: AlertRecoveryAdmission
    promotion_digest: Digest


@dataclass(frozen=True, slots=True)
class AdmittedAlertAuthority:
    """Public content addresses and pseudonymous decisions; never expose a Var OID snapshot."""

    proof: AdmittedAlertRecord
    approvals: tuple[AlertApproval, ...]
    dispatch: AlertDispatchEvidence | AlertRecoveryAdmission
    process_id: str
    approval_step_id: str
    attempt: int
    approval_snapshot_digest: str
    promotion: ActionModeRecord
    approval_valid_until: datetime
    identity_binding_digest: str


def alert_dispatch_binding(
    *,
    action: Action,
    plan: AlertChangePlan,
    pr: RemediationPr,
    authority: AdmittedAlertAuthority,
    evidence_receipt_digest: str | None,
    evaluation_admission_digest: str | None,
) -> dict[str, object]:
    """Describe exact dispatch proof, including actual Var and registry revisions.

    A governed verifier must resolve risk, scope, actor rights, observers, tested rollback,
    kill switch and every referenced proof. Computing this statement grants nothing.
    Recovery deliberately has no current forward-evidence or forward-evaluation admission.
    """
    promotion = asdict(authority.promotion)
    for name in ("promoted_at", "demoted_at"):
        value = promotion[name]
        promotion[name] = value.isoformat() if isinstance(value, datetime) else None
    return {
        "action_digest": full_action_digest(action),
        "plan_digest": digest_record(plan),
        "publication_digest": alert_publication_digest(plan, pr),
        "authority_digest": authority.proof.admission.evidence_digest,
        "authority_receipt_digest": authority.proof.receipt_digest,
        "approval_snapshot_digest": authority.approval_snapshot_digest,
        "identity_binding_digest": authority.identity_binding_digest,
        "promotion_record_digest": content_digest(promotion),
        "dispatch_evidence_digest": digest_record(authority.dispatch),
        "approval_receipt_refs": sorted(item.receipt_ref for item in authority.approvals),
        "evidence_digest": plan.evidence_digest,
        "evidence_receipt_digest": evidence_receipt_digest,
        "evaluation_receipt_digest": plan.evaluation_receipt_digest,
        "evaluation_admission_digest": evaluation_admission_digest,
        "execution_authority": False,
    }
