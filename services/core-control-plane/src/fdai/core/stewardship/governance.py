"""Idempotent stewardship draft delivery through the governance PR publisher.

A handover draft never changes the active ownership map. This service renders
one review-only draft PR for `config/agent-stewardship.yaml` and publishes it
through the generic `RemediationPrPublisher`, so every ownership change stays a
human-reviewed GitOps merge.

Delivery is idempotent by the content-addressed artifact key: a retry after an
ambiguous transport failure reuses the same draft PR instead of opening a
second one. An abstained draft is never published.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import yaml
from fdai_service_contracts.handover import HandoverDraftArtifact, HandoverDraftOutcome

from fdai.core.stewardship.model import StewardshipValidationError
from fdai.core.stewardship.resolver import load_stewardship_from_mapping
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)

STEWARDSHIP_PATCH_PATH = "config/agent-stewardship.yaml"
STEWARDSHIP_LABELS = ("shadow", "stewardship-handover")
_MAX_YAML_BYTES = 256 * 1024
_MAX_BODY_WARNINGS = 20


class StewardshipGovernanceError(RuntimeError):
    """Raised when a draft cannot become a review-only governance PR."""


@dataclass(frozen=True, slots=True)
class StewardshipGovernanceResult:
    """Outcome of one governance publish attempt."""

    published: bool
    receipt: PublishReceipt | None
    idempotency_key: str
    reason: str | None = None


def stewardship_idempotency_key(artifact: HandoverDraftArtifact) -> str:
    """Return the stable content-addressed key for one draft artifact."""

    digest = hashlib.sha256()
    for part in (
        str(artifact.upload_id),
        str(artifact.document_id),
        str(artifact.version_id),
        artifact.yaml,
    ):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")
    return f"stewardship-handover:{digest.hexdigest()}"


@dataclass(frozen=True, slots=True)
class StewardshipGovernanceService:
    """Publish a stewardship draft as one idempotent, review-only PR."""

    publisher: RemediationPrPublisher
    validation_environ: Mapping[str, str] = field(default_factory=dict)

    async def publish(self, artifact: HandoverDraftArtifact) -> StewardshipGovernanceResult:
        key = stewardship_idempotency_key(artifact)
        if artifact.draft.outcome is not HandoverDraftOutcome.DRAFTED:
            return StewardshipGovernanceResult(
                published=False,
                receipt=None,
                idempotency_key=key,
                reason="abstained_draft",
            )
        if not artifact.draft.mappings:
            return StewardshipGovernanceResult(
                published=False,
                receipt=None,
                idempotency_key=key,
                reason="no_mapping",
            )
        if not artifact.yaml.strip():
            raise StewardshipGovernanceError("stewardship draft YAML MUST be non-empty")
        if len(artifact.yaml.encode("utf-8")) > _MAX_YAML_BYTES:
            raise StewardshipGovernanceError("stewardship draft YAML exceeds the bounded size")
        validate_stewardship_candidate(artifact.yaml, environ=self.validation_environ)
        receipt = await self.publisher.publish(_render(artifact, key))
        return StewardshipGovernanceResult(
            published=True,
            receipt=receipt,
            idempotency_key=key,
        )


def _render(artifact: HandoverDraftArtifact, key: str) -> RemediationPr:
    draft = artifact.draft
    lines = [
        "Review-only stewardship handover draft.",
        "",
        f"Document: {artifact.document_id}",
        f"Version: {artifact.version_id}",
        f"Proposed mappings: {len(draft.mappings)}",
        f"Abstained mappings: {len(draft.abstained)}",
        f"Unresolved people: {len(draft.unresolved_people)}",
        f"Unmapped agents: {len(draft.unmapped_agents)}",
        "",
        "This draft changes no active ownership until a human merges it.",
    ]
    if draft.warnings:
        shown = tuple(draft.warnings[:_MAX_BODY_WARNINGS])
        lines.extend(("", "Warnings:", *(f"- {warning}" for warning in shown)))
        if len(draft.warnings) > len(shown):
            lines.append(f"- ... {len(draft.warnings) - len(shown)} more warning(s) truncated")
    return RemediationPr(
        action_id=_action_id(key),
        idempotency_key=key,
        rule_ids=("stewardship-handover",),
        title=f"Stewardship handover draft for {len(draft.mappings)} agent binding(s)",
        body="\n".join(lines),
        patch=artifact.yaml,
        patch_path=STEWARDSHIP_PATCH_PATH,
        labels=STEWARDSHIP_LABELS,
        mode=Mode.SHADOW,
        metadata={
            "upload_id": str(artifact.upload_id),
            "document_id": str(artifact.document_id),
            "version_id": str(artifact.version_id),
            "schema_version": artifact.schema_version,
        },
    )


def validate_stewardship_candidate(
    candidate: str,
    *,
    environ: Mapping[str, str],
) -> Any:
    """Return a complete stewardship map or fail closed."""

    try:
        raw: Any = yaml.safe_load(candidate)
    except yaml.YAMLError as exc:
        raise StewardshipGovernanceError("stewardship draft YAML is malformed") from exc
    if not isinstance(raw, Mapping):
        raise StewardshipGovernanceError("stewardship draft YAML MUST be a mapping")
    validation_environ = {}
    require_bindings = environ.get("FDAI_STEWARDSHIP_REQUIRE_BINDINGS")
    if require_bindings is not None:
        validation_environ["FDAI_STEWARDSHIP_REQUIRE_BINDINGS"] = require_bindings
    try:
        return load_stewardship_from_mapping(raw, environ=validation_environ)
    except StewardshipValidationError as exc:
        raise StewardshipGovernanceError(
            "stewardship draft YAML failed governance validation"
        ) from exc


def _action_id(key: str) -> UUID:
    return UUID(bytes=hashlib.sha256(key.encode("utf-8")).digest()[:16], version=4)


__all__ = [
    "STEWARDSHIP_LABELS",
    "STEWARDSHIP_PATCH_PATH",
    "StewardshipGovernanceError",
    "StewardshipGovernanceResult",
    "StewardshipGovernanceService",
    "stewardship_idempotency_key",
    "validate_stewardship_candidate",
]
