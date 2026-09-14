"""Describe exact lock trust and writer-exclusion bindings without manufacturing their proof."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Annotated, Any

from fdai_service_contracts.alert_noise import Ref, digest_record
from fdai_service_contracts.alert_noise_base import AlertContractBase, AlertTime, FalseOnly
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.executor_models import Digest
from pydantic import Field

from fdai.core.detection.alert_noise.execution import alert_publication_digest
from fdai.core.executor.safeguards import full_action_digest
from fdai.delivery.alert_noise_evidence import alert_scope_digest
from fdai.shared.contracts.models import Action
from fdai.shared.providers.remediation_pr import RemediationPr

ALERT_WRITER_EXCLUSIVITY_PURPOSE = "alert-noise-writer-exclusivity"


@dataclass(frozen=True, slots=True)
class AlertLockTrust:
    """Composition-pinned identities of the real evidenced lock provider and verifier."""

    provider_id: str
    provider_version: str
    verifier_id: str
    verifier_version: str
    trust_anchor_id: str

    def __post_init__(self) -> None:
        """Reject incomplete or normalized trust identities before acquiring any lock."""
        for value in (
            self.provider_id,
            self.provider_version,
            self.verifier_id,
            self.verifier_version,
            self.trust_anchor_id,
        ):
            if (
                type(value) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}", value) is None
            ):
                raise ValueError("alert lock trust identities MUST be explicit")


class _WriterExclusion(AlertContractBase):
    binding: dict[str, Any]
    writer_ref: Ref
    mechanism_ref: Ref
    restriction_digest: Digest
    generation: Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]
    exclusive_from: AlertTime
    exclusive_until: AlertTime
    release_not_before: AlertTime
    release_ref: Ref
    released_at: AlertTime | None
    dispatch_receipt_digest: Digest
    execution_authority: FalseOnly


def alert_writer_binding(
    *,
    action: Action,
    plan: AlertChangePlan,
    pr: RemediationPr,
    repository_ref: str,
    repository_revision: str,
) -> dict[str, object]:
    """Describe exact provider and repository exclusion; a computed digest is not its proof."""
    return {
        "action_digest": full_action_digest(action),
        "plan_digest": digest_record(plan),
        "publication_digest": alert_publication_digest(plan, pr),
        "repository_ref": repository_ref,
        "repository_revision": repository_revision,
        "path": pr.patch_path,
        "source_digest": pr.metadata.get("source_digest"),
        "result_digest": pr.metadata.get("result_digest"),
        "patch_digest": "sha256:" + hashlib.sha256(pr.patch.encode("utf-8")).hexdigest(),
        "dependency_refs": list(plan.lock_refs),
        "policy_digest": plan.policy_digest,
        "target_revision": plan.target_revision,
        "executor_ref": action.executor_identity_ref,
        "scope_digest": alert_scope_digest(tenant_ref=plan.tenant_ref, scope_ref=plan.scope_ref),
        "execution_authority": False,
    }
