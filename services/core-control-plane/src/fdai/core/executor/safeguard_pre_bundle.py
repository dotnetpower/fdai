"""Immutable pre-bundle commitment created before executor selection.

The commitment binds the complete Action, selected execution path, execution
fingerprint, and source revision. It proves only what was fixed before target
locking starts. It does not claim that any safeguard proof exists and grants no
execution or effect-verification authority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, Self, runtime_checkable

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.safeguards import execution_fingerprint, full_action_digest
from fdai.shared.contracts.models import Action, ExecutionPath

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_REVISION = re.compile(r"^commit:[a-f0-9]{40}(?:[a-f0-9]{24})?$")


@dataclass(frozen=True, slots=True)
class SafeguardPreBundleCommitment:
    """Action-bound immutable commitment that precedes target-lock acquisition."""

    schema_version: Literal["1.0.0"]
    action_digest: str
    execution_path: ExecutionPath
    execution_fingerprint: str
    source_revision: str
    committed_at: datetime
    commitment_digest: str
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("unsupported safeguard pre-bundle commitment schema")
        if self.execution_authority is not False or self.effect_verification_authority is not False:
            raise ValueError("safeguard pre-bundle commitment MUST NOT grant authority")
        if _DIGEST.fullmatch(self.action_digest) is None:
            raise ValueError("pre-bundle action digest MUST be SHA-256")
        if type(self.execution_path) is not ExecutionPath:
            raise ValueError("pre-bundle execution path is invalid")
        if _FINGERPRINT.fullmatch(self.execution_fingerprint) is None:
            raise ValueError("pre-bundle execution fingerprint MUST be lowercase SHA-256")
        if _SOURCE_REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("pre-bundle source revision MUST be canonical")
        if self.committed_at.tzinfo is None or self.committed_at.utcoffset() is None:
            raise ValueError("pre-bundle committed_at MUST include a timezone")
        if self.committed_at.utcoffset() != UTC.utcoffset(self.committed_at):
            raise ValueError("pre-bundle committed_at MUST be normalized to UTC")
        if _DIGEST.fullmatch(self.commitment_digest) is None:
            raise ValueError("pre-bundle commitment digest MUST be SHA-256")
        if self.commitment_digest != _commitment_digest(self):
            raise ValueError("pre-bundle commitment digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        action: Action,
        execution_path: ExecutionPath,
        source_revision: str,
        committed_at: datetime,
    ) -> Self:
        """Create a no-authority commitment from the exact dispatch Action."""

        if cls is not SafeguardPreBundleCommitment:
            raise TypeError("safeguard pre-bundle commitment does not support subclasses")
        normalized_at = _utc(committed_at)
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "action_digest": full_action_digest(action),
            "execution_path": execution_path,
            "execution_fingerprint": execution_fingerprint(
                action=action,
                execution_path=execution_path,
            ),
            "source_revision": source_revision,
            "committed_at": normalized_at,
            "execution_authority": False,
            "effect_verification_authority": False,
        }
        values["commitment_digest"] = _payload_digest(values)
        return cls(**values)  # type: ignore[arg-type]

    def require_matches(
        self,
        *,
        action: Action,
        execution_path: ExecutionPath,
        source_revision: str,
    ) -> None:
        """Reject a substituted action, path, fingerprint, or source revision."""

        if (
            self.action_digest != full_action_digest(action)
            or self.execution_path is not execution_path
            or self.execution_fingerprint
            != execution_fingerprint(action=action, execution_path=execution_path)
            or self.source_revision != source_revision
        ):
            raise ValueError("safeguard pre-bundle commitment changed dispatch context")


@runtime_checkable
class SafeguardPreBundleCommitmentStore(Protocol):
    """Persist and resolve one workflow commitment before executor selection."""

    async def read(
        self,
        *,
        process_id: str,
        step_id: str,
        attempt: int,
    ) -> SafeguardPreBundleCommitment | None:
        """Read the exact workflow step-attempt commitment."""
        ...

    async def bind(
        self,
        *,
        process_id: str,
        step_id: str,
        attempt: int,
        correlation_id: str,
        commitment: SafeguardPreBundleCommitment,
    ) -> SafeguardPreBundleCommitment:
        """Persist once or return the exact existing commitment."""
        ...


def safeguard_pre_bundle_commitment_to_mapping(
    commitment: SafeguardPreBundleCommitment,
) -> dict[str, object]:
    """Serialize one canonical commitment for durable workflow evidence."""

    if type(commitment) is not SafeguardPreBundleCommitment:
        raise ValueError("pre-bundle serializer requires an exact commitment")
    return {
        "schema_version": commitment.schema_version,
        "action_digest": commitment.action_digest,
        "execution_path": commitment.execution_path.value,
        "execution_fingerprint": commitment.execution_fingerprint,
        "source_revision": commitment.source_revision,
        "committed_at": commitment.committed_at.isoformat(),
        "commitment_digest": commitment.commitment_digest,
        "execution_authority": False,
        "effect_verification_authority": False,
    }


def safeguard_pre_bundle_commitment_from_mapping(
    value: Mapping[str, object],
) -> SafeguardPreBundleCommitment:
    """Reconstruct and validate one durable workflow commitment."""

    expected = {
        "schema_version",
        "action_digest",
        "execution_path",
        "execution_fingerprint",
        "source_revision",
        "committed_at",
        "commitment_digest",
        "execution_authority",
        "effect_verification_authority",
    }
    if set(value) != expected:
        raise ValueError("pre-bundle commitment fields are incomplete")
    try:
        committed_at = datetime.fromisoformat(str(value["committed_at"]))
        path = ExecutionPath(str(value["execution_path"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("pre-bundle commitment fields are malformed") from exc
    return SafeguardPreBundleCommitment(
        schema_version=str(value["schema_version"]),  # type: ignore[arg-type]
        action_digest=str(value["action_digest"]),
        execution_path=path,
        execution_fingerprint=str(value["execution_fingerprint"]),
        source_revision=str(value["source_revision"]),
        committed_at=committed_at,
        commitment_digest=str(value["commitment_digest"]),
        execution_authority=value["execution_authority"],  # type: ignore[arg-type]
        effect_verification_authority=value["effect_verification_authority"],  # type: ignore[arg-type]
    )


def _utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("pre-bundle committed_at MUST include a timezone")
    return value.astimezone(UTC)


def _payload_digest(values: Mapping[str, object]) -> str:
    body = dict(values)
    body.pop("commitment_digest", None)
    normalized = {
        key: (
            item.astimezone(UTC).isoformat()
            if isinstance(item, datetime)
            else item.value
            if isinstance(item, ExecutionPath)
            else item
        )
        for key, item in body.items()
    }
    return content_digest({"domain": "safeguard-pre-bundle-commitment", "body": normalized})


def _commitment_digest(commitment: SafeguardPreBundleCommitment) -> str:
    return _payload_digest(asdict(commitment))


__all__ = [
    "SafeguardPreBundleCommitment",
    "SafeguardPreBundleCommitmentStore",
    "safeguard_pre_bundle_commitment_from_mapping",
    "safeguard_pre_bundle_commitment_to_mapping",
]
