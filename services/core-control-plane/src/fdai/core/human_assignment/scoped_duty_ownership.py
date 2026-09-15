"""Reviewed scoped artifacts and current read-only ownership observations, never IAM effects."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from fdai.core.human_assignment.scoped_duties import canonical_json, utc_instant
from fdai.core.human_assignment.scoped_duty_case_model import (
    ScopedDutyCase,
    plan_expiry,
    require_current_plan,
)
from fdai.core.human_assignment.scoped_duty_case_service import ScopedDutyCaseService
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import RemediationPr, RemediationPrPublisher
from fdai.shared.providers.resource_lock import ResourceLock


@dataclass(frozen=True, slots=True)
class ScopedDutyMergeObservation:
    """Current provider-authenticated exact artifact readback; no execution or role authority."""

    pr_ref: str
    path: str
    candidate_digest: str
    merge_commit_sha: str
    observed_at: datetime
    expires_at: datetime


class ScopedDutyMergeReader(Protocol):
    """Verify exact reviewed merge and current default-branch content independently of publish."""

    async def read(
        self,
        *,
        pr_ref: str,
        path: str,
        candidate_digest: str,
    ) -> ScopedDutyMergeObservation | None:
        """Return current authenticated evidence only; closed-unmerged or changed content holds."""
        ...


def scoped_artifact(case: ScopedDutyCase) -> tuple[str, str, str]:
    """Render the same immutable review artifact before or after draft delivery.

    Only declaration and review inputs participate; case revision and PR effects do not
    rewrite the candidate on replay. The private repository owns all deployment values.
    """
    path = f"config/scoped-duty-plans/{UUID(case.case_id)}.json"
    content = (
        canonical_json(
            {
                "schema_version": "1.0.0",
                "kind": "reviewed_scoped_duty_plan",
                "case_id": case.case_id,
                "request": case.request.model_dump(mode="json"),
                "plan": case.plan(),
                "reviews": [row.model_dump(mode="json") for row in case.reviews],
                "execution_authority": False,
                "iam_authority": False,
                "global_map_authority": False,
            }
        )
        + "\n"
    )
    return path, content, hashlib.sha256(content.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ScopedDutyOwnership:
    """Consume sealed two-Owner cases into a draft PR and independently checked projection.

    This does not install a global or scoped authorization map. An exact verified merge
    supplies read-only accountability evidence; current identity, scope, roles and time
    still gate every projection. Personal IAM requests require their separate lifecycle.
    """

    cases: ScopedDutyCaseService
    publisher: RemediationPrPublisher
    locks: ResourceLock
    merges: ScopedDutyMergeReader

    async def open_proposal(self, case_id: str, *, expected_revision: int) -> ScopedDutyCase:
        """Open one independently reviewed draft under a target lock and two-phase audit.

        A persisted candidate plus stable publisher key recovers uncertain publication;
        changes to sources, reviewers or content hold instead of opening a second draft.
        No method merges the PR or changes a person, role, duty map, or promotion registry.
        """
        async with asyncio.timeout(self.cases.planner.policy.total_timeout_seconds):
            async with self.locks.acquire("scoped-duty-artifact:" + case_id):
                current = await self.cases.get(case_id)
                if current.state not in {"approved", "ownership_pr_open"}:
                    raise ValueError("scoped artifact requires a two-Owner reviewed case")
                if current.revision != expected_revision:
                    raise ValueError("scoped artifact case revision changed")
                observation = await self.cases.check_review(
                    current,
                    actor=current.reviews[0].reviewer_ref,
                    plan_digest=current.plan()["digest"],
                )
                path, content, digest = scoped_artifact(current)
                if current.pr_ref is not None:
                    if current.candidate_digest != digest:
                        raise ValueError("scoped artifact does not match its retained intent")
                    return current
                key = "human_assignment:scoped-artifact-intent:" + case_id
                intent = {"case_id": case_id, "candidate_digest": digest, "path": path}
                retained = await self.cases.store.read_state(key)
                if retained is not None and retained != intent:
                    raise ValueError("scoped artifact candidate conflicts with its original intent")
                if retained is None:
                    await self.cases.store.write_state_with_audit_if_absent(
                        key,
                        intent,
                        self.cases.audit(current, "artifact_intent", "artifact-delivery"),
                    )
                    if await self.cases.store.read_state(key) != intent:
                        raise ValueError("scoped artifact intent did not persist")
                if await self.cases.get(case_id) != current:
                    raise ValueError("scoped artifact source changed before publication")
                require_current_plan(observation, at=self.cases.clock())
                receipt = await self.publisher.publish(
                    RemediationPr(
                        action_id=UUID(case_id),
                        idempotency_key="scoped-duty-artifact:" + case_id,
                        rule_ids=("human.assignment.scoped-duty",),
                        title="Review scoped operational duties",
                        body=(
                            "This is an ownership-only review artifact. It grants no IAM role "
                            "or execution authority and cannot change the global map. A changed "
                            "source stops consumption. Rollback is a separately reviewed artifact "
                            "removal or replacement; a missing or changed current artifact "
                            "withdraws its projection. The dry-run is the exact current coverage "
                            "plan retained in this artifact. Independent merge and current source "
                            "observation are required before any coverage is presented."
                        ),
                        patch=content,
                        patch_path=path,
                        mode=Mode.SHADOW,
                        labels=("shadow", "governance", "ownership"),
                        metadata={"scoped_case_id": case_id, "candidate_digest": digest},
                    )
                )
                candidate = self.cases.changed(
                    current,
                    state="ownership_pr_open",
                    pr_ref=receipt.pr_ref,
                    candidate_digest=digest,
                )
                # Publishing a draft has no ownership effect. Even if evidence expires in
                # flight, retain the exact delivery fact so recovery never duplicates it.
                if await self.cases.store.compare_and_set_state_with_audit(
                    "human_assignment:scoped-case:" + case_id,
                    candidate.model_dump(mode="json"),
                    expected_revision=current.revision,
                    audit_entry=self.cases.audit(candidate, "artifact_opened", "artifact-delivery"),
                ):
                    return candidate
                winner = await self.cases.get(case_id)
                if winner.pr_ref != receipt.pr_ref or winner.candidate_digest != digest:
                    raise ValueError("scoped artifact delivery needs exact replay recovery")
                return winner

    async def observe(self, current: ScopedDutyCase) -> tuple[dict[str, object], ...]:
        """Consume the exact merged artifact into scoped read observations, without a writer."""
        if current.state != "ownership_pr_open" or current.pr_ref is None:
            return ()
        path, _content, digest = scoped_artifact(current)
        if current.candidate_digest != digest:
            raise ValueError("scoped artifact candidate changed")
        async with asyncio.timeout(self.cases.planner.policy.total_timeout_seconds):
            merge = await self.merges.read(
                pr_ref=current.pr_ref, path=path, candidate_digest=digest
            )
            if merge is None:
                return ()
            observation = await self.cases.check_review(
                current,
                actor=current.reviews[0].reviewer_ref,
                plan_digest=current.plan()["digest"],
            )
            at = utc_instant(self.cases.clock())
            if (
                merge.pr_ref != current.pr_ref
                or merge.path != path
                or merge.candidate_digest != digest
                or not utc_instant(merge.observed_at) <= at < utc_instant(merge.expires_at)
                or await self.cases.get(current.case_id) != current
            ):
                raise ValueError("scoped merge observation is expired or mismatched")
            require_current_plan(observation, at=self.cases.clock())
            expires = min(merge.expires_at, plan_expiry(observation))
            return tuple(
                {
                    **row,
                    "case_id": current.case_id,
                    "case_revision": current.revision,
                    "source_revision": current.request.source_revision,
                    "candidate_digest": digest,
                    "merge_commit_sha": merge.merge_commit_sha,
                    "pr_ref": merge.pr_ref,
                    "observed_at": at.isoformat(),
                    "expires_at": expires.isoformat(),
                    "execution_authority": False,
                }
                for row in observation["coverage"]
            )


__all__ = [
    "ScopedDutyMergeObservation",
    "ScopedDutyMergeReader",
    "ScopedDutyOwnership",
    "scoped_artifact",
]
