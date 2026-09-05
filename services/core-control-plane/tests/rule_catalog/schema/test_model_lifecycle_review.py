from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fdai.composition._helpers import LlmBindingsUnavailableError
from fdai.composition.resolved_models import _load_resolved_models
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.rule_catalog.schema.model_lifecycle_review import (
    ModelLifecycleProposalReview,
    ModelLifecycleReviewStatus,
    evaluate_model_lifecycle_review,
)
from fdai.runtime.model_lifecycle_startup import resolve_models_startup_revision
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 23, tzinfo=UTC)
_PROPOSAL_DIGEST = "a" * 64
_SOURCE_DIGEST = "b" * 64


def _proposal(**changes: object) -> ModelLifecycleProposalReview:
    values: dict[str, object] = {
        "proposal_digest": _PROPOSAL_DIGEST,
        "source_models_digest": _SOURCE_DIGEST,
        "affected_capabilities": ("t1.embedding", "t2.reasoner.primary"),
        "opened_at": _NOW,
        "expires_at": _NOW + timedelta(days=7),
        "merged_at": None,
    }
    values.update(changes)
    return ModelLifecycleProposalReview(**values)  # type: ignore[arg-type]


def test_active_proposal_does_not_hold_current_mapping() -> None:
    decision = evaluate_model_lifecycle_review(
        _proposal(),
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=_NOW + timedelta(days=6),
    )

    assert decision.status is ModelLifecycleReviewStatus.ACTIVE
    assert decision.held_capabilities == ()
    assert decision.mapping_authority is False
    assert decision.execution_authority is False


def test_expiry_boundary_holds_only_declared_capabilities() -> None:
    proposal = _proposal(affected_capabilities=("t2.reasoner.primary",))

    decision = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=proposal.expires_at,
    )

    assert decision.status is ModelLifecycleReviewStatus.HOLD
    assert decision.reason_code == "proposal_expired_unmerged"
    assert decision.held_capabilities == ("t2.reasoner.primary",)


def test_merged_proposal_does_not_hold() -> None:
    proposal = _proposal(merged_at=_NOW + timedelta(days=2))

    decision = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=_NOW + timedelta(days=8),
    )

    assert decision.status is ModelLifecycleReviewStatus.MERGED
    assert decision.held_capabilities == ()


def test_superseded_source_does_not_hold_new_mapping() -> None:
    decision = evaluate_model_lifecycle_review(
        _proposal(),
        current_models_digest="c" * 64,
        evaluated_at=_NOW + timedelta(days=8),
    )

    assert decision.status is ModelLifecycleReviewStatus.STALE_SOURCE
    assert decision.reason_code == "proposal_source_superseded"
    assert decision.held_capabilities == ()


@pytest.mark.parametrize(
    ("proposal", "evaluated_at", "status", "reason_code"),
    [
        (
            _proposal(),
            _NOW + timedelta(days=1),
            ModelLifecycleReviewStatus.ACTIVE,
            "proposal_review_active",
        ),
        (
            _proposal(),
            _NOW + timedelta(days=7),
            ModelLifecycleReviewStatus.HOLD,
            "proposal_expired_unmerged",
        ),
        (
            _proposal(merged_at=_NOW + timedelta(days=1)),
            _NOW + timedelta(days=2),
            ModelLifecycleReviewStatus.MERGED,
            "proposal_merged",
        ),
    ],
)
def test_every_current_source_decision_has_no_authority(
    proposal: ModelLifecycleProposalReview,
    evaluated_at: datetime,
    status: ModelLifecycleReviewStatus,
    reason_code: str,
) -> None:
    decision = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=evaluated_at,
    )

    assert decision.status is status
    assert decision.reason_code == reason_code
    assert decision.mapping_authority is False
    assert decision.execution_authority is False


def test_decision_digest_is_replay_stable() -> None:
    proposal = _proposal()
    first = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=proposal.expires_at,
    )
    second = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=proposal.expires_at,
    )

    assert first == second
    assert len(first.decision_digest) == 64


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"proposal_digest": "invalid"}, "proposal_digest"),
        ({"source_models_digest": "invalid"}, "source_models_digest"),
        ({"affected_capabilities": ()}, "at least one"),
        (
            {"affected_capabilities": ("t2.reasoner.primary", "t1.embedding")},
            "unique and sorted",
        ),
        ({"affected_capabilities": ("invalid",)}, "bounded T1/T2"),
        ({"expires_at": _NOW}, "after opened_at"),
        ({"opened_at": datetime(2026, 8, 23)}, "timezone-aware"),
        ({"merged_at": _NOW - timedelta(seconds=1)}, "MUST NOT precede"),
        ({"merged_at": _NOW + timedelta(days=8)}, "MUST NOT be after expires_at"),
    ],
)
def test_proposal_rejects_invalid_boundary(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _proposal(**changes)


def test_evaluation_rejects_future_merge_observation() -> None:
    proposal = _proposal(merged_at=_NOW + timedelta(days=2))

    with pytest.raises(ValueError, match="after evaluated_at"):
        evaluate_model_lifecycle_review(
            proposal,
            current_models_digest=_SOURCE_DIGEST,
            evaluated_at=_NOW + timedelta(days=1),
        )


@dataclass(frozen=True)
class _Artifact:
    content: str
    digest: str
    secret_version: str | None = "version1"


class _Source:
    def __init__(self, artifact: _Artifact) -> None:
        self.artifact = artifact
        self.loads = 0

    async def load(self) -> _Artifact:
        self.loads += 1
        return self.artifact


def _resolved_content() -> str:
    return ResolvedModels(
        schema_version="1.0.0",
        region="example-region",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000000",
        mixed_model_mode="hil-only",
        capabilities=(
            ResolvedCapability(
                name="t1.judge",
                status=CapabilityStatus.RESOLVED,
                publisher="OpenAI",
                family="example-family",
                sku="Standard",
                capacity_tpm=1,
                invocation="always",
            ),
        ),
    ).to_json()


def _observation(content: str, *, trusted: bool = True) -> dict[str, object]:
    source_digest = hashlib.sha256(
        json.dumps(json.loads(content), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    proposal: dict[str, object] = {
        "schema_version": "fdai.model-lifecycle-proposal.v3",
        "status": "proposal",
        "activation_authority": False,
        "source_models_digest": source_digest,
        "affected_capabilities": ["t1.judge"],
        "changes": [],
        "deprecations": [],
        "compatibility_impact": [],
        "proposal_digest": None,
    }
    proposal["proposal_digest"] = hashlib.sha256(
        json.dumps(proposal, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "trusted": trusted,
        "pull_request": 257,
        "head_sha": "1" * 40,
        "opened_at": _NOW.isoformat(),
        "expires_at": (_NOW + timedelta(days=1)).isoformat(),
        "merged_at": None,
        "proposal": proposal,
    }


@pytest.mark.asyncio
async def test_startup_owner_loads_once_persists_verified_hold_before_binding() -> None:
    content = _resolved_content()
    artifact = _Artifact(content, hashlib.sha256(content.encode()).hexdigest())
    source = _Source(artifact)
    store = InMemoryStateStore()

    revision = await resolve_models_startup_revision(
        source,
        expected_artifact_digest=artifact.digest,
        observations=(_observation(content),),
        decision_store=store,
        evaluated_at=_NOW + timedelta(days=1),
    )

    assert source.loads == 1
    assert revision.held_capabilities == ("t1.judge",)
    assert revision.bindable_capability("t1.judge") is None
    assert revision.mapping_authority is False
    assert revision.execution_authority is False
    stored = await store.find_state("model-lifecycle-review:", field="status", value="hold")
    assert stored is not None
    assert stored["decision_digest"] == revision.decisions[0].decision_digest


@pytest.mark.asyncio
async def test_startup_owner_rejects_untrusted_or_mismatched_revision() -> None:
    content = _resolved_content()
    artifact = _Artifact(content, hashlib.sha256(content.encode()).hexdigest())
    store = InMemoryStateStore()

    with pytest.raises(ValueError, match="deployment binding"):
        await resolve_models_startup_revision(
            _Source(artifact),
            expected_artifact_digest="0" * 64,
            observations=(),
            decision_store=store,
            evaluated_at=_NOW,
        )
    with pytest.raises(ValueError, match="MUST be trusted"):
        await resolve_models_startup_revision(
            _Source(artifact),
            expected_artifact_digest=artifact.digest,
            observations=(_observation(content, trusted=False),),
            decision_store=store,
            evaluated_at=_NOW,
        )


def test_core_rejects_source_revision_mismatch_before_model_binding() -> None:
    content = _resolved_content()

    assert _load_resolved_models(
        content,
        expected_digest=hashlib.sha256(content.encode()).hexdigest(),
    ).capabilities
    with pytest.raises(LlmBindingsUnavailableError, match="source revision"):
        _load_resolved_models(content, expected_digest="0" * 64)
