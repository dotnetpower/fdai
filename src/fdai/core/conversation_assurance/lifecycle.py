"""Bounded autonomous lifecycle for chat-only assurance policy candidates."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from fdai.core.conversation_assurance.learning import FailureCluster, cluster_failures
from fdai.core.conversation_assurance.models import AssessmentRecord
from fdai.core.conversation_assurance.policy_store import ConversationPolicyCandidateStore
from fdai.core.conversation_assurance.promotion import (
    ChatPolicyCandidate,
    ChatPolicyTarget,
    PolicyTransition,
    PolicyTrialMetrics,
    PromotionConfig,
    evaluate_policy_transition,
)


@dataclass(frozen=True, slots=True)
class ChatPolicyProposal:
    target: ChatPolicyTarget
    policy_digest: str
    incumbent_policy_digest: str

    def __post_init__(self) -> None:
        if len(self.policy_digest) != 64 or len(self.incumbent_policy_digest) != 64:
            raise ValueError("policy proposal digests MUST be 64 characters")


class ChatPolicyProposer(Protocol):
    async def propose(self, cluster: FailureCluster) -> ChatPolicyProposal | None: ...


class BlindPolicyTrialMeasurer(Protocol):
    async def measure(
        self,
        candidate: ChatPolicyCandidate,
        cluster: FailureCluster,
    ) -> PolicyTrialMetrics | None: ...


class ChatPolicyPublisher(Protocol):
    async def publish(
        self,
        candidate: ChatPolicyCandidate,
        transition: PolicyTransition,
    ) -> None: ...

    async def restore(
        self,
        candidate: ChatPolicyCandidate,
        transition: PolicyTransition,
    ) -> None: ...


class ConversationAssuranceLifecycleRunner(Protocol):
    async def run(
        self,
        records: tuple[AssessmentRecord, ...],
    ) -> tuple[ChatPolicyCandidate, ...]: ...


class ConversationAssuranceLifecycleCoordinator:
    """Cluster scoped failures and advance only measured chat-policy candidates."""

    def __init__(
        self,
        *,
        store: ConversationPolicyCandidateStore,
        proposer: ChatPolicyProposer,
        measurer: BlindPolicyTrialMeasurer,
        publisher: ChatPolicyPublisher,
        promotion_config: PromotionConfig | None = None,
        min_cluster_samples: int = 3,
    ) -> None:
        self._store = store
        self._proposer = proposer
        self._measurer = measurer
        self._publisher = publisher
        self._promotion_config = promotion_config
        self._min_cluster_samples = min_cluster_samples

    async def run(
        self,
        records: tuple[AssessmentRecord, ...],
    ) -> tuple[ChatPolicyCandidate, ...]:
        results: list[ChatPolicyCandidate] = []
        for cluster in cluster_failures(records, min_samples=self._min_cluster_samples):
            proposal = await self._proposer.propose(cluster)
            if proposal is None:
                continue
            candidate = _candidate(cluster, proposal)
            await self._store.append_candidate(candidate)
            stored = await self._store.get_candidate(
                principal_scope=cluster.principal_scope,
                candidate_id=candidate.candidate_id,
            )
            if stored is None:
                raise RuntimeError("policy candidate lost after idempotent append")
            metrics = await self._measurer.measure(stored, cluster)
            if metrics is None:
                results.append(stored)
                continue
            transition = evaluate_policy_transition(
                stored,
                metrics,
                config=self._promotion_config,
            )
            if transition.to_stage is transition.from_stage:
                results.append(
                    await self._store.apply_transition(
                        principal_scope=cluster.principal_scope,
                        transition=transition,
                    )
                )
                continue
            await self._publisher.publish(stored, transition)
            try:
                updated = await self._store.apply_transition(
                    principal_scope=cluster.principal_scope,
                    transition=transition,
                )
            except Exception as store_error:
                try:
                    await self._publisher.restore(stored, transition)
                except Exception as restore_error:
                    raise ExceptionGroup(
                        "policy transition persistence and restore failed",
                        (store_error, restore_error),
                    ) from None
                raise
            results.append(updated)
        return tuple(results)


def _candidate(
    cluster: FailureCluster,
    proposal: ChatPolicyProposal,
) -> ChatPolicyCandidate:
    material = "\0".join(
        (
            cluster.principal_scope,
            cluster.cluster_id,
            proposal.target.value,
            proposal.policy_digest,
            proposal.incumbent_policy_digest,
        )
    )
    candidate_id = "assurance-candidate:" + hashlib.sha256(material.encode()).hexdigest()
    return ChatPolicyCandidate(
        candidate_id=candidate_id,
        principal_scope=cluster.principal_scope,
        cluster_id=cluster.cluster_id,
        target=proposal.target,
        policy_digest=proposal.policy_digest,
        incumbent_policy_digest=proposal.incumbent_policy_digest,
    )


__all__ = [
    "BlindPolicyTrialMeasurer",
    "ChatPolicyProposal",
    "ChatPolicyProposer",
    "ChatPolicyPublisher",
    "ConversationAssuranceLifecycleCoordinator",
    "ConversationAssuranceLifecycleRunner",
]
