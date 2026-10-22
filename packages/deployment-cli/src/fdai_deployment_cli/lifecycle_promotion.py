"""Release channel promotion pipeline evaluator and boundary registry digest mirroring."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from fdai_deployment_cli.lifecycle_plan import required_artifact_digests
from fdai_deployment_cli.lifecycle_release import LifecycleRelease
from fdai_deployment_cli.runtime_release import (
    RecallRecord,
    ReleaseDecision,
    evaluate_recall_candidate,
    is_release_id,
)

_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionStageCriteria:
    """Criteria required to advance a Release from ``source_channel`` to ``target_channel``."""

    source_channel: str
    target_channel: str
    required_labels: frozenset[str] = field(default_factory=frozenset)
    min_soak_seconds: int = 0
    min_healthy_canaries: int = 0
    max_stage_timeout_seconds: int = 3600

    def __post_init__(self) -> None:
        if not self.source_channel.strip() or not self.target_channel.strip():
            raise ValueError("source_channel and target_channel MUST NOT be empty")
        if self.source_channel == self.target_channel:
            raise ValueError("source_channel and target_channel MUST differ")
        if any(not label.strip() for label in self.required_labels):
            raise ValueError("required_labels MUST NOT contain blank labels")
        if (
            isinstance(self.min_soak_seconds, bool)
            or not isinstance(self.min_soak_seconds, int)
            or self.min_soak_seconds < 0
        ):
            raise ValueError("min_soak_seconds MUST be a non-negative integer")
        if (
            isinstance(self.min_healthy_canaries, bool)
            or not isinstance(self.min_healthy_canaries, int)
            or self.min_healthy_canaries < 0
        ):
            raise ValueError("min_healthy_canaries MUST be a non-negative integer")
        if (
            isinstance(self.max_stage_timeout_seconds, bool)
            or not isinstance(self.max_stage_timeout_seconds, int)
            or self.max_stage_timeout_seconds < 1
        ):
            raise ValueError("max_stage_timeout_seconds MUST be a positive integer")


@dataclass(frozen=True, slots=True, kw_only=True)
class CanaryObservation:
    """Health and soak observation from one canary installation running a candidate Release."""

    installation_id: str
    release_id: str
    healthy: bool
    soak_seconds: int

    def __post_init__(self) -> None:
        if not self.installation_id.strip():
            raise ValueError("installation_id MUST NOT be empty")
        if not is_release_id(self.release_id):
            raise ValueError("release_id MUST be canonical SemVer")
        if not isinstance(self.healthy, bool):
            raise TypeError("healthy MUST be a boolean")
        if (
            isinstance(self.soak_seconds, bool)
            or not isinstance(self.soak_seconds, int)
            or self.soak_seconds < 0
        ):
            raise ValueError("soak_seconds MUST be a non-negative integer")


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionStageInput:
    """Observed evidence for one promotion-pipeline stage evaluation."""

    release_id: str
    present_in_source_channel: bool
    labels: frozenset[str] = field(default_factory=frozenset)
    canary_observations: tuple[CanaryObservation, ...] = ()
    elapsed_stage_seconds: int = 0
    capability_ids: tuple[str, ...] = ()
    recall_records: tuple[RecallRecord, ...] = ()

    def __post_init__(self) -> None:
        if not is_release_id(self.release_id):
            raise ValueError("release_id MUST be canonical SemVer")
        if not isinstance(self.present_in_source_channel, bool):
            raise TypeError("present_in_source_channel MUST be a boolean")
        if (
            isinstance(self.elapsed_stage_seconds, bool)
            or not isinstance(self.elapsed_stage_seconds, int)
            or self.elapsed_stage_seconds < 0
        ):
            raise ValueError("elapsed_stage_seconds MUST be a non-negative integer")


def evaluate_promotion_stage(
    criteria: PromotionStageCriteria,
    stage_input: PromotionStageInput,
) -> ReleaseDecision:
    """Evaluate label requirements, soak time, canary health, timeouts, and recalls."""

    recall_decision = evaluate_recall_candidate(
        release_id=stage_input.release_id,
        capability_ids=stage_input.capability_ids,
        recall_records=stage_input.recall_records,
    )
    if not recall_decision.allowed:
        return recall_decision
    if not stage_input.present_in_source_channel:
        return ReleaseDecision(
            False, "promotion_source_channel_missing", (criteria.source_channel,)
        )
    if stage_input.elapsed_stage_seconds > criteria.max_stage_timeout_seconds:
        return ReleaseDecision(
            False,
            "promotion_stage_timed_out",
            (str(stage_input.elapsed_stage_seconds), str(criteria.max_stage_timeout_seconds)),
        )
    missing_labels = tuple(sorted(criteria.required_labels - stage_input.labels))
    if missing_labels:
        return ReleaseDecision(False, "promotion_labels_missing", missing_labels)
    relevant = [
        obs for obs in stage_input.canary_observations if obs.release_id == stage_input.release_id
    ]
    unhealthy = tuple(sorted(obs.installation_id for obs in relevant if not obs.healthy))
    if unhealthy:
        return ReleaseDecision(False, "promotion_canary_unhealthy", unhealthy)
    healthy = [obs for obs in relevant if obs.healthy]
    if len(healthy) < criteria.min_healthy_canaries:
        return ReleaseDecision(
            False,
            "promotion_canary_quorum_unmet",
            (str(len(healthy)), str(criteria.min_healthy_canaries)),
        )
    soaked = [obs for obs in healthy if obs.soak_seconds >= criteria.min_soak_seconds]
    if len(soaked) < criteria.min_healthy_canaries:
        return ReleaseDecision(
            False,
            "promotion_soak_incomplete",
            (str(len(soaked)), str(criteria.min_healthy_canaries)),
        )
    return ReleaseDecision(True, "allowed", ())


@dataclass(frozen=True, slots=True)
class BoundaryRegistryMirror:
    """Connected-installation boundary registry mirror state for Release image digests."""

    mirrored_digests: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if any(_IMAGE_DIGEST.fullmatch(digest) is None for digest in self.mirrored_digests):
            raise ValueError("mirrored_digests MUST contain only sha256:<64 hex> digests")

    def missing_for(self, release: LifecycleRelease) -> frozenset[str]:
        """Return required Release image digests not yet mirrored inside the boundary."""

        return required_artifact_digests(release) - self.mirrored_digests

    def mirror_release(
        self,
        release: LifecycleRelease,
        *,
        available_upstream_digests: Iterable[str],
    ) -> BoundaryRegistryMirror:
        """Mirror available required digests for ``release`` into the boundary registry."""

        upstream = frozenset(available_upstream_digests)
        if any(_IMAGE_DIGEST.fullmatch(digest) is None for digest in upstream):
            raise ValueError("available_upstream_digests MUST contain only sha256:<64 hex> digests")
        required = required_artifact_digests(release)
        transferred = required & upstream
        return BoundaryRegistryMirror(mirrored_digests=self.mirrored_digests | transferred)
