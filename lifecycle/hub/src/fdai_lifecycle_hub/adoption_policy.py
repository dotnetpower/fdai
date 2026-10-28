"""Rego-governed decision on whether a verified catalog may be adopted without a person.

The Hub computes a bounded change summary and asks the packaged Rego policy for a decision. The
policy engine is the same ``opa`` binary the Core uses. Every failure path denies, so an engine
that is missing, slow or wrong sends the candidate to review and never adopts it silently.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fdai_deployment_cli.runtime_release import RecallRecord
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai_lifecycle_hub.catalog import ReleaseCatalog

POLICY_PATH = Path(__file__).with_name("policy") / "catalog_adoption.rego"
POLICY_QUERY = "data.fdai.lifecycle.catalog_adoption.decision"
OPA_TIMEOUT_SECONDS = 5.0
_CHANNEL = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class AdoptionConfig(BaseModel):
    """The owner's standing authorization, supplied by reviewed deployment configuration."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    mode: Literal["review", "auto"] = "review"
    allowed_channels: tuple[str, ...] = ()
    max_new_releases: int = Field(default=3, ge=0, le=64)
    authorized_by: str | None = Field(default=None, min_length=1, max_length=160)
    authorization_expires_at: str | None = None

    @model_validator(mode="after")
    def validate_authorization(self) -> AdoptionConfig:
        if any(_CHANNEL.fullmatch(name) is None for name in self.allowed_channels):
            raise ValueError("Adoption channels must be canonical channel names.")
        if len(set(self.allowed_channels)) != len(self.allowed_channels):
            raise ValueError("Adoption channels must be unique.")
        if self.authorization_expires_at is not None:
            expires = datetime.fromisoformat(self.authorization_expires_at)
            if expires.tzinfo is None:
                raise ValueError("Authorization expiry must include a timezone.")
        if self.mode == "auto" and (
            self.authorized_by is None or self.authorization_expires_at is None
        ):
            raise ValueError("Automatic adoption needs an attributed, expiring authorization.")
        return self

    def authorization_valid(self, now: datetime) -> bool:
        if self.authorized_by is None or self.authorization_expires_at is None:
            return False
        return datetime.fromisoformat(self.authorization_expires_at) > now


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allow: bool
    reasons: tuple[str, ...]


def _recall_key(recall: RecallRecord) -> tuple[Any, ...]:
    return (
        recall.scope,
        recall.target,
        recall.sequence,
        recall.action,
        recall.notice_digest,
    )


def _schema_ceiling(catalog: ReleaseCatalog | None) -> int:
    if catalog is None:
        return 0
    ceiling = 0
    for release in catalog.releases.values():
        ceiling = max(ceiling, release.schema_target or 0)
        if release.schema_range is not None:
            ceiling = max(ceiling, release.schema_range.maximum)
    return ceiling


def summarize_change(previous: ReleaseCatalog | None, candidate: ReleaseCatalog) -> dict[str, Any]:
    """Describe only what differs, using ids and digests and never manifest content."""

    old_releases = dict(previous.releases) if previous else {}
    old_channels = dict(previous.channels) if previous else {}
    old_recalls = {_recall_key(item) for item in previous.recalls} if previous else set()

    def memberships(release_id: str) -> list[str]:
        return sorted(name for name, members in candidate.channels.items() if release_id in members)

    added = sorted(set(candidate.releases) - set(old_releases))
    changed = sorted(
        release_id
        for release_id, release in candidate.releases.items()
        if release_id in old_releases and old_releases[release_id].digest != release.digest
    )
    additions = [
        {"channel": name, "release_id": release_id}
        for name, members in sorted(candidate.channels.items())
        for release_id in sorted(members - old_channels.get(name, frozenset()))
    ]
    removals = [
        {"channel": name, "release_id": release_id}
        for name, members in sorted(old_channels.items())
        for release_id in sorted(members - candidate.channels.get(name, frozenset()))
    ]
    fresh_recalls = [item for item in candidate.recalls if _recall_key(item) not in old_recalls]
    kept_recalls = {_recall_key(item) for item in candidate.recalls}
    dropped_recalls = [
        {"scope": key[0], "target": key[1], "sequence": key[2]}
        for key in sorted(old_recalls - kept_recalls)
    ]
    return {
        "added_releases": [
            {
                "release_id": release_id,
                "channels": memberships(release_id),
                "schema_target": candidate.releases[release_id].schema_target,
            }
            for release_id in added
        ],
        "removed_releases": sorted(set(old_releases) - set(candidate.releases)),
        "changed_releases": changed,
        "channel_additions": additions,
        "channel_removals": removals,
        "new_channels": sorted(set(candidate.channels) - set(old_channels)),
        "new_recalls": [
            {"scope": item.scope, "target": item.target, "sequence": item.sequence}
            for item in fresh_recalls
            if item.action == "recall"
        ],
        "lifted_recalls": [
            {"scope": item.scope, "target": item.target, "sequence": item.sequence}
            for item in fresh_recalls
            if item.action == "lift"
        ],
        "removed_recalls": dropped_recalls,
        "schema_widened": previous is not None
        and _schema_ceiling(candidate) > _schema_ceiling(previous),
    }


def policy_input(
    *,
    config: AdoptionConfig,
    change: dict[str, Any],
    baseline_present: bool,
    signature_verified: bool,
    now: datetime,
    integrity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "signature": {"verified": signature_verified},
        "baseline_present": baseline_present,
        "now": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "config": {
            "mode": config.mode,
            "allowed_channels": list(config.allowed_channels),
            "max_new_releases": config.max_new_releases,
            "authorized_by": config.authorized_by,
            "authorization_expires_at": config.authorization_expires_at,
        },
        "change": change,
    }
    if integrity is not None:
        document["integrity"] = integrity
    return document


def evaluate_policy(
    document: dict[str, Any],
    *,
    opa_binary: str = "opa",
    timeout: float = OPA_TIMEOUT_SECONDS,
) -> PolicyDecision:
    """Ask Rego for a decision. A missing, failing or malformed engine denies."""

    resolved = shutil.which(opa_binary)
    if resolved is None:
        return PolicyDecision(False, ("policy_engine_unavailable",))
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argument vector, no shell
            [
                resolved,
                "eval",
                "--stdin-input",
                "--format",
                "json",
                "--data",
                str(POLICY_PATH),
                POLICY_QUERY,
            ],
            input=json.dumps(document).encode(),
            capture_output=True,
            timeout=timeout,
            check=False,
            env={},
        )
        if completed.returncode != 0:
            return PolicyDecision(False, ("policy_evaluation_failed",))
        value = json.loads(completed.stdout)["result"][0]["expressions"][0]["value"]
        allow, reasons = value["allow"], value["reasons"]
        if (
            type(allow) is not bool
            or not isinstance(reasons, list)
            or not all(isinstance(item, str) for item in reasons)
        ):
            return PolicyDecision(False, ("policy_result_invalid",))
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError, TypeError):
        return PolicyDecision(False, ("policy_evaluation_failed",))
    if allow != (not reasons):
        return PolicyDecision(False, ("policy_result_invalid",))
    return PolicyDecision(allow, tuple(reasons))


def decision_record(decision: PolicyDecision) -> dict[str, Any]:
    return asdict(decision) | {"reasons": list(decision.reasons)}
