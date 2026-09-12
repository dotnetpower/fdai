"""Trusted import boundary for Cost Governance campaign observations."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

from fdai.shared.providers.cost_governance_campaign import (
    CostCampaignEpisode,
    CostCampaignOutcome,
    CostCampaignSettlement,
    CostCampaignStore,
)
from fdai.shared.providers.cost_governance_lifecycle import (
    CostEvidenceKind,
    CostRevisionPin,
)

_CAMPAIGN_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_WORKFLOW_PATH = re.compile(r"^\.github/workflows/[a-z0-9][a-z0-9-]{0,99}\.yml$")
_ARTIFACT_NAME = re.compile(r"^cost-governance-observations-[a-z0-9][a-z0-9-]{0,99}$")
_MAX_BATCH_BYTES = 8 * 1024 * 1024
_MAX_CAMPAIGN_EPISODES = 10_000
_OBSERVATION_FIELDS = frozenset(
    {
        "audit_complete",
        "decision_correct",
        "effect_path_complete",
        "episode_id",
        "evidence_refs",
        "hard_dependencies_complete",
        "objective_regression",
        "observed_at",
        "ontology_competency_passed",
        "outcome",
        "parity_explained",
        "policy_escape",
        "policy_excluded",
        "protected_objectives_complete",
        "reason",
        "recovery_attempts",
        "rollback_evidence_complete",
        "safeguards_complete",
        "settlement_statuses",
        "target_refs",
        "topic_owner_correct",
        "unauthorized_disclosure",
    }
)


@dataclass(frozen=True, slots=True)
class CostCampaignImportPolicy:
    """Bound trusted exporters and retention without granting review authority."""

    policy_id: str
    policy_version: str
    allowed_exporter_workflow_paths: tuple[str, ...]
    maximum_window_seconds: int
    maximum_batch_episodes: int
    retention_days: int
    digest: str


@dataclass(frozen=True, slots=True)
class CostCampaignImportContext:
    """Trusted workflow coordinates that the source artifact cannot supply."""

    source_workflow_path: str
    source_run_id: int
    source_run_attempt: int
    source_artifact_name: str
    imported_at: datetime

    def __post_init__(self) -> None:
        if _WORKFLOW_PATH.fullmatch(self.source_workflow_path) is None:
            raise ValueError("campaign source workflow path is invalid")
        if self.source_run_id < 1 or self.source_run_attempt < 1:
            raise ValueError("campaign source run identity MUST be positive")
        if _ARTIFACT_NAME.fullmatch(self.source_artifact_name) is None:
            raise ValueError("campaign source artifact name is invalid")
        if self.imported_at.tzinfo is None or self.imported_at.utcoffset() is None:
            raise ValueError("campaign import time MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class CostCampaignObservationBatch:
    """Bounded source observations without caller-controlled trust fields."""

    campaign_id: str
    revision_pin_digest: str
    observations: tuple[MappingProxyType[str, object], ...]
    batch_digest: str


@dataclass(frozen=True, slots=True)
class CostCampaignImportReport:
    """Aggregate-only import result with no approval or promotion authority."""

    campaign_id: str
    batch_digest: str
    accepted_count: int
    duplicate_count: int

    def to_mapping(self) -> dict[str, object]:
        return {
            "accepted_count": self.accepted_count,
            "batch_digest": self.batch_digest,
            "campaign_id": self.campaign_id,
            "duplicate_count": self.duplicate_count,
            "approval_authority": False,
            "promotion_authority": False,
        }


class CostCampaignImportConflictError(RuntimeError):
    """An episode identity was reused with different immutable evidence."""


def load_cost_campaign_import_policy(path: Path) -> CostCampaignImportPolicy:
    """Load one strict repository-owned importer policy."""

    document = _load_json(path, maximum_bytes=_MAX_BATCH_BYTES, label="campaign policy")
    expected_keys = {
        "allowed_exporter_workflow_paths",
        "maximum_batch_episodes",
        "maximum_window_seconds",
        "policy_id",
        "policy_version",
        "retention_days",
        "schema_version",
    }
    if set(document) != expected_keys or document.get("schema_version") != "1.0.0":
        raise ValueError("campaign policy fields are invalid")
    workflows = document["allowed_exporter_workflow_paths"]
    if (
        not isinstance(workflows, list)
        or not workflows
        or len(workflows) != len(set(workflows))
        or any(
            not isinstance(item, str) or _WORKFLOW_PATH.fullmatch(item) is None
            for item in workflows
        )
    ):
        raise ValueError("campaign exporter workflow allowlist is invalid")
    maximum_window_seconds = _integer(document, "maximum_window_seconds", 60, 15_552_000)
    maximum_batch_episodes = _integer(document, "maximum_batch_episodes", 1, 1_000)
    retention_days = _integer(document, "retention_days", 90, 2_555)
    policy_id = _text(document, "policy_id", 128)
    policy_version = _text(document, "policy_version", 32)
    return CostCampaignImportPolicy(
        policy_id=policy_id,
        policy_version=policy_version,
        allowed_exporter_workflow_paths=tuple(workflows),
        maximum_window_seconds=maximum_window_seconds,
        maximum_batch_episodes=maximum_batch_episodes,
        retention_days=retention_days,
        digest=_canonical_digest(document),
    )


def load_cost_campaign_observation_batch(
    path: Path,
    *,
    maximum_episodes: int,
) -> CostCampaignObservationBatch:
    """Load and content-verify one normalized observation batch."""

    document = _load_json(path, maximum_bytes=_MAX_BATCH_BYTES, label="campaign batch")
    if set(document) != {
        "batch_digest",
        "campaign_id",
        "observations",
        "revision_pin_digest",
        "schema_version",
    }:
        raise ValueError("campaign batch fields are invalid")
    if document.get("schema_version") != "1.0.0":
        raise ValueError("campaign batch schema_version MUST be 1.0.0")
    campaign_id = _text(document, "campaign_id", 128)
    if _CAMPAIGN_ID.fullmatch(campaign_id) is None:
        raise ValueError("campaign_id is invalid")
    revision_pin_digest = _text(document, "revision_pin_digest", 71)
    if _DIGEST.fullmatch(revision_pin_digest) is None:
        raise ValueError("campaign revision_pin_digest is invalid")
    observations = document.get("observations")
    if not isinstance(observations, list) or not 1 <= len(observations) <= maximum_episodes:
        raise ValueError("campaign observations exceed the configured bound")
    normalized: list[MappingProxyType[str, object]] = []
    episode_ids: set[str] = set()
    for item in observations:
        if not isinstance(item, dict) or set(item) != _OBSERVATION_FIELDS:
            raise ValueError("campaign observation fields are invalid")
        episode_id = _text(item, "episode_id", 512)
        if episode_id in episode_ids:
            raise ValueError("campaign observation episode ids MUST be unique")
        episode_ids.add(episode_id)
        normalized.append(MappingProxyType(dict(item)))
    batch_digest = document.get("batch_digest")
    expected = _canonical_digest(
        {key: value for key, value in document.items() if key != "batch_digest"}
    )
    if batch_digest != expected:
        raise ValueError("campaign batch digest does not match its content")
    return CostCampaignObservationBatch(
        campaign_id=campaign_id,
        revision_pin_digest=revision_pin_digest,
        observations=tuple(normalized),
        batch_digest=expected,
    )


async def import_cost_campaign_observations(
    batch: CostCampaignObservationBatch,
    *,
    revision_pin: CostRevisionPin,
    context: CostCampaignImportContext,
    policy: CostCampaignImportPolicy,
    allowed_target_ids: frozenset[str],
    store: CostCampaignStore,
) -> CostCampaignImportReport:
    """Bind trusted source provenance and append terminal observations idempotently."""

    if context.source_workflow_path not in policy.allowed_exporter_workflow_paths:
        raise ValueError("campaign source workflow is not authorized")
    if batch.revision_pin_digest != revision_pin.digest:
        raise ValueError("campaign batch revision pin does not match the active release")
    imported_at = context.imported_at.astimezone(UTC)
    earliest = imported_at - timedelta(seconds=policy.maximum_window_seconds)
    retained = await store.read_cost_campaign_episodes(
        batch.campaign_id,
        revision_pin.digest,
        limit=10_000,
    )
    existing = {item.episode_id: item for item in retained}
    incoming_ids = {_text(item, "episode_id", 512) for item in batch.observations}
    if len(existing) + len(incoming_ids - existing.keys()) > _MAX_CAMPAIGN_EPISODES:
        raise ValueError("campaign exceeds the retained episode bound")
    accepted = duplicate = 0
    for raw in batch.observations:
        observed_at = _timestamp(raw["observed_at"])
        if observed_at < earliest or observed_at > imported_at:
            raise ValueError("campaign observation falls outside the import window")
        targets = _string_tuple(raw["target_refs"], "target_refs")
        if not targets or not set(targets) <= allowed_target_ids:
            raise ValueError("campaign observation target_refs are not package-owned")
        episode_id = _text(raw, "episode_id", 512)
        observation_digest = _canonical_digest(dict(raw))
        source_identity = _canonical_digest(
            {
                "campaign_id": batch.campaign_id,
                "episode_id": episode_id,
                "observation_digest": observation_digest,
                "policy_digest": policy.digest,
                "revision_pin_digest": revision_pin.digest,
                "source_workflow_path": context.source_workflow_path,
            }
        )
        episode = CostCampaignEpisode(
            schema_version="1.0.0",
            campaign_id=batch.campaign_id,
            episode_id=episode_id,
            revision=1,
            idempotency_key=f"w7:{source_identity.removeprefix('sha256:')}",
            revision_pin_digest=revision_pin.digest,
            evidence_kind=CostEvidenceKind.LIVE_AUTHORITATIVE,
            outcome=CostCampaignOutcome(_text(raw, "outcome", 64)),
            reason=_text(raw, "reason", 512),
            target_refs=targets,
            settlement_statuses=tuple(
                CostCampaignSettlement(item)
                for item in _string_tuple(raw["settlement_statuses"], "settlement_statuses")
            ),
            recovery_attempts=_integer(raw, "recovery_attempts", 0, 7),
            policy_excluded=_boolean(raw, "policy_excluded"),
            policy_escape=_boolean(raw, "policy_escape"),
            objective_regression=_boolean(raw, "objective_regression"),
            audit_complete=_boolean(raw, "audit_complete"),
            hard_dependencies_complete=_boolean(raw, "hard_dependencies_complete"),
            unauthorized_disclosure=_boolean(raw, "unauthorized_disclosure"),
            ontology_competency_passed=_boolean(raw, "ontology_competency_passed"),
            topic_owner_correct=_boolean(raw, "topic_owner_correct"),
            protected_objectives_complete=_boolean(raw, "protected_objectives_complete"),
            safeguards_complete=_boolean(raw, "safeguards_complete"),
            effect_path_complete=_boolean(raw, "effect_path_complete"),
            parity_explained=_boolean(raw, "parity_explained"),
            rollback_evidence_complete=_boolean(raw, "rollback_evidence_complete"),
            decision_correct=_boolean(raw, "decision_correct"),
            observed_at=observed_at,
            evidence_refs=(
                *_source_evidence_refs(raw["evidence_refs"]),
                f"observation:{observation_digest}",
                f"policy:{policy.digest}",
                f"workflow:{context.source_workflow_path}:{context.source_run_id}:{context.source_run_attempt}",
                f"artifact:{context.source_artifact_name}:{batch.batch_digest}",
            ),
            retention_until=observed_at + timedelta(days=policy.retention_days),
        )
        prior = existing.get(episode_id)
        if prior is not None:
            if not _same_observation(prior, episode, observation_digest=observation_digest):
                raise CostCampaignImportConflictError(
                    "campaign episode identity was reused with different evidence"
                )
            duplicate += 1
            continue
        if not await store.append_cost_campaign_episode(episode, expected_revision=0):
            raise CostCampaignImportConflictError("campaign episode append conflicted")
        existing[episode_id] = episode
        accepted += 1
    return CostCampaignImportReport(
        campaign_id=batch.campaign_id,
        batch_digest=batch.batch_digest,
        accepted_count=accepted,
        duplicate_count=duplicate,
    )


def _load_json(path: Path, *, maximum_bytes: int, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum_bytes:
        raise ValueError(f"{label} is unavailable or exceeds the byte limit")
    try:
        value = json.loads(path.read_bytes(), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} MUST contain an object")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON object repeats key: {key}")
        result[key] = value
    return result


def _text(value: Mapping[str, object], key: str, maximum: int) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.isascii() or not 1 <= len(item) <= maximum:
        raise ValueError(f"{key} MUST be bounded non-empty ASCII")
    return item


def _integer(value: Mapping[str, object], key: str, minimum: int, maximum: int) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or not minimum <= item <= maximum:
        raise ValueError(f"{key} MUST be an integer in [{minimum}, {maximum}]")
    return item


def _boolean(value: Mapping[str, object], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"{key} MUST be a boolean")
    return item


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.isascii() or not 1 <= len(item) <= 512
        for item in value
    ):
        raise ValueError(f"{name} MUST be a bounded ASCII string array")
    return tuple(value)


def _source_evidence_refs(value: object) -> tuple[str, ...]:
    refs = _string_tuple(value, "evidence_refs")
    if not 1 <= len(refs) <= 60 or len(refs) != len(set(refs)):
        raise ValueError("evidence_refs MUST contain 1..60 unique source references")
    return refs


def _same_observation(
    prior: CostCampaignEpisode,
    candidate: CostCampaignEpisode,
    *,
    observation_digest: str,
) -> bool:
    prior_body = prior.to_mapping()
    candidate_body = candidate.to_mapping()
    prior_body.pop("evidence_refs")
    candidate_body.pop("evidence_refs")
    return (
        prior_body == candidate_body
        and f"observation:{observation_digest}" in prior.evidence_refs
    )


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("observed_at MUST be RFC3339 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at MUST be RFC3339 text") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at MUST include a timezone")
    return parsed.astimezone(UTC)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "CostCampaignImportConflictError",
    "CostCampaignImportContext",
    "CostCampaignImportPolicy",
    "CostCampaignImportReport",
    "CostCampaignObservationBatch",
    "import_cost_campaign_observations",
    "load_cost_campaign_import_policy",
    "load_cost_campaign_observation_batch",
]