"""Own immutable resolved-model loading and lifecycle holds at startup."""

from __future__ import annotations

import hashlib
import json
import re
from asyncio import to_thread
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.rule_catalog.schema.model_lifecycle_review import (
    ModelLifecycleProposalReview,
    ModelLifecycleReviewDecision,
    evaluate_model_lifecycle_review,
)
from fdai.shared.providers.state_store import StateStore

_HEAD_SHA = re.compile(r"^[a-f0-9]{40}$")
_PROPOSAL_SCHEMA = "fdai.model-lifecycle-proposal.v3"
_DIGEST = re.compile(r"^[a-f0-9]{64}$")


class ResolvedModelsArtifact(Protocol):
    """Expose immutable resolved-model bytes from an asynchronous source."""

    @property
    def content(self) -> str: ...

    @property
    def digest(self) -> str: ...

    @property
    def secret_version(self) -> str | None: ...


class AsyncResolvedModelsSource(Protocol):
    """Load one immutable resolved-model artifact during startup."""

    async def load(self) -> ResolvedModelsArtifact: ...


@dataclass(frozen=True, slots=True)
class FileResolvedModelsArtifact:
    """Carry one immutable file revision through startup."""

    content: str
    digest: str
    secret_version: str | None = None


@dataclass(frozen=True, slots=True)
class FileResolvedModelsSource:
    """Load the existing inline or deployment-mounted model revision once."""

    path_or_content: str
    maximum_bytes: int = 1_048_576

    async def load(self) -> FileResolvedModelsArtifact:
        if self.path_or_content.lstrip().startswith("{"):
            content = self.path_or_content.encode("utf-8")
        else:
            content = await to_thread(Path(self.path_or_content).read_bytes)
        if len(content) > self.maximum_bytes:
            raise ValueError("resolved-model artifact exceeds the startup byte limit")
        return FileResolvedModelsArtifact(
            content=content.decode("utf-8"),
            digest=hashlib.sha256(content).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class ResolvedModelsStartupRevision:
    """Publish one source revision to lifecycle review and capability binding."""

    models: ResolvedModels
    source_models_digest: str
    artifact_digest: str
    secret_version: str | None
    held_capabilities: tuple[str, ...]
    decisions: tuple[ModelLifecycleReviewDecision, ...]
    mapping_authority: bool = False
    execution_authority: bool = False

    def bindable_capability(self, name: str) -> ResolvedCapability | None:
        """Return a capability only when startup review did not hold it."""

        if name in self.held_capabilities:
            return None
        return next(
            (
                item
                for item in self.models.capabilities
                if item.name == name and item.status is not CapabilityStatus.HIL_ONLY
            ),
            None,
        )


async def resolve_models_startup_revision(
    source: AsyncResolvedModelsSource,
    *,
    expected_artifact_digest: str,
    observations: tuple[Mapping[str, object], ...],
    decision_store: StateStore,
    evaluated_at: datetime,
) -> ResolvedModelsStartupRevision:
    """Load once, verify trusted PR observations, persist decisions, and publish holds."""

    _require_digest(expected_artifact_digest, "expected_artifact_digest")
    artifact = await source.load()
    _require_digest(artifact.digest, "artifact_digest")
    if artifact.digest != expected_artifact_digest:
        raise ValueError("resolved-model artifact digest does not match deployment binding")
    try:
        payload = json.loads(artifact.content)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("resolved-model startup artifact is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("resolved-model startup artifact MUST be an object")
    source_models_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    models = ResolvedModels.from_json(artifact.content)
    decisions: list[ModelLifecycleReviewDecision] = []
    held: set[str] = set()
    for observation in observations:
        proposal = _trusted_proposal(observation)
        decision = evaluate_model_lifecycle_review(
            proposal,
            current_models_digest=source_models_digest,
            evaluated_at=evaluated_at,
        )
        _verify_decision_digest(decision)
        await _persist_decision(decision_store, observation, decision)
        decisions.append(decision)
        held.update(decision.held_capabilities)
    return ResolvedModelsStartupRevision(
        models=models,
        source_models_digest=source_models_digest,
        artifact_digest=artifact.digest,
        secret_version=artifact.secret_version,
        held_capabilities=tuple(sorted(held)),
        decisions=tuple(decisions),
    )


def _trusted_proposal(observation: Mapping[str, object]) -> ModelLifecycleProposalReview:
    if observation.get("trusted") is not True:
        raise ValueError("model lifecycle observation MUST be trusted")
    pull_request = observation.get("pull_request")
    if isinstance(pull_request, bool) or not isinstance(pull_request, int) or pull_request < 1:
        raise ValueError("model lifecycle observation pull_request is invalid")
    head_sha = observation.get("head_sha")
    if not isinstance(head_sha, str) or _HEAD_SHA.fullmatch(head_sha) is None:
        raise ValueError("model lifecycle observation head_sha is invalid")
    raw = observation.get("proposal")
    if not isinstance(raw, Mapping):
        raise ValueError("model lifecycle observation proposal is invalid")
    if (
        raw.get("schema_version") != _PROPOSAL_SCHEMA
        or raw.get("status") != "proposal"
        or raw.get("activation_authority") is not False
    ):
        raise ValueError("model lifecycle observation proposal contract is invalid")
    proposal_digest = raw.get("proposal_digest")
    if not isinstance(proposal_digest, str):
        raise ValueError("model lifecycle proposal_digest is invalid")
    digest_input = dict(raw)
    digest_input["proposal_digest"] = None
    observed_digest = hashlib.sha256(
        json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if observed_digest != proposal_digest:
        raise ValueError("model lifecycle proposal digest verification failed")
    source_digest = raw.get("source_models_digest")
    affected = raw.get("affected_capabilities")
    if (
        not isinstance(source_digest, str)
        or not isinstance(affected, list)
        or not all(isinstance(item, str) for item in affected)
    ):
        raise ValueError("model lifecycle proposal source or capabilities are invalid")
    opened_at = _observation_time(observation, "opened_at", required=True)
    expires_at = _observation_time(observation, "expires_at", required=True)
    if opened_at is None or expires_at is None:  # pragma: no cover - required invariant
        raise AssertionError("required lifecycle observation time is absent")
    return ModelLifecycleProposalReview(
        proposal_digest=proposal_digest,
        source_models_digest=source_digest,
        affected_capabilities=tuple(affected),
        opened_at=opened_at,
        expires_at=expires_at,
        merged_at=_observation_time(observation, "merged_at", required=False),
    )


def _observation_time(
    observation: Mapping[str, object],
    field: str,
    *,
    required: bool,
) -> datetime | None:
    raw = observation.get(field)
    if raw is None and not required:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"model lifecycle observation {field} is invalid")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"model lifecycle observation {field} is invalid") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"model lifecycle observation {field} MUST be timezone-aware")
    return value


def _verify_decision_digest(decision: ModelLifecycleReviewDecision) -> None:
    body = {
        "status": decision.status.value,
        "reason_code": decision.reason_code,
        "held_capabilities": decision.held_capabilities,
        "proposal_digest": decision.proposal_digest,
        "source_models_digest": decision.source_models_digest,
        "evaluated_at": decision.evaluated_at.isoformat(),
        "mapping_authority": decision.mapping_authority,
        "execution_authority": decision.execution_authority,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if digest != decision.decision_digest:
        raise ValueError("model lifecycle decision digest verification failed")


async def _persist_decision(
    store: StateStore,
    observation: Mapping[str, object],
    decision: ModelLifecycleReviewDecision,
) -> None:
    key = (
        f"model-lifecycle-review:{decision.proposal_digest}:"
        f"{decision.source_models_digest}:{decision.decision_digest}"
    )
    value = {
        "schema_version": "fdai.model-lifecycle-review-decision.v1",
        "pull_request": observation["pull_request"],
        "head_sha": observation["head_sha"],
        "status": decision.status.value,
        "reason_code": decision.reason_code,
        "held_capabilities": list(decision.held_capabilities),
        "proposal_digest": decision.proposal_digest,
        "source_models_digest": decision.source_models_digest,
        "evaluated_at": decision.evaluated_at.isoformat(),
        "decision_digest": decision.decision_digest,
        "mapping_authority": False,
        "execution_authority": False,
    }
    if await store.write_state_if_absent(key, value):
        return
    existing = await store.read_state(key)
    if existing is None or existing.get("decision_digest") != decision.decision_digest:
        raise ValueError("model lifecycle decision persistence conflict")


def _require_digest(value: str, field: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"model lifecycle {field} MUST be a lowercase SHA-256 digest")


__all__ = [
    "AsyncResolvedModelsSource",
    "FileResolvedModelsArtifact",
    "FileResolvedModelsSource",
    "ResolvedModelsArtifact",
    "ResolvedModelsStartupRevision",
    "resolve_models_startup_revision",
]
