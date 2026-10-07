"""Signed Release and configuration package inputs for one admitted Plan.

Both inputs are verified before any change is computed (ADR-0003 A15). The signature covers the
exact file bytes. The digest that the Plan names is the SHA-256 of the canonical JSON of the
document, as the Hub computes it (``RuntimeRelease.digest`` and ``canonical_digest`` of the
configuration). A missing or failed signature, a digest that differs from the Plan, or a malformed
document rejects the Plan with a stable reason code.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, get_args

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_configuration import (
    ConfigurationValidationError,
    validate_configuration_package_for_signing,
)
from fdai_deployment_cli.lifecycle_plan import (
    CapabilityMode,
    LifecycleEffectEnvelope,
    LifecyclePlan,
)

from fdai_lifecycle_agent.signatures import ArtifactVerifier
from fdai_lifecycle_agent.strict_json import load_json, read_limited

LIFECYCLE_RELEASE_SCHEMA = "fdai.runtime-release.v3"
MAX_INPUT_BYTES = 1024 * 1024
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_IMAGE_SECTIONS = ("services", "sidecars", "installation_agents")
# The shared contract declares capability modes from least to most authority; a test pins this
# order to LifecycleEffectEnvelope.narrowed_by so the two can't drift apart.
_AUTHORITY: tuple[CapabilityMode, ...] = get_args(CapabilityMode)

type InputKind = Literal["release", "configuration"]


class InputProblem(StrEnum):
    UNAVAILABLE = "unavailable"
    UNREADABLE = "unreadable"
    SIGNATURE_MISSING = "signature_missing"
    SIGNATURE_INVALID = "signature_invalid"
    DIGEST_MISMATCH = "digest_mismatch"
    MALFORMED = "malformed"
    SCHEMA_UNSUPPORTED = "schema_unsupported"
    LITERAL_SECRET = "literal_secret"  # noqa: S105 - a reason code, not a secret


# Inputs that can appear later, for example after a registry or file sync, don't block a Plan.
_RETRYABLE_PROBLEMS = frozenset({InputProblem.UNAVAILABLE, InputProblem.UNREADABLE})


class InputRejectedError(Exception):
    """A signed input failed verification; carries only a stable reason code."""

    def __init__(self, kind: InputKind, problem: InputProblem) -> None:
        self.reason_code = f"{kind}_{problem}"
        self.problem = problem
        super().__init__(self.reason_code)

    @property
    def retryable(self) -> bool:
        return self.problem in _RETRYABLE_PROBLEMS


@dataclass(frozen=True, slots=True)
class SignedArtifact:
    """Raw artifact bytes with a detached signature. An empty signature means unsigned."""

    payload: bytes
    signature: bytes


class ArtifactStore(Protocol):
    """Read-only source of signed Releases and configuration packages inside the installation.

    Implementations return ``None`` for an absent artifact and raise ``OSError`` when it exists
    but can't be read.
    """

    def load(self, kind: InputKind, digest: str) -> SignedArtifact | None: ...


class DirectoryArtifactStore:
    """Read ``releases/<digest>.json`` and ``configurations/<digest>.json`` below one root.

    Each document has a sibling ``<digest>.sig`` file with the raw Ed25519 signature. A missing
    signature file yields an unsigned artifact so the caller can reject it explicitly.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def load(self, kind: InputKind, digest: str) -> SignedArtifact | None:
        if _HEX_DIGEST.fullmatch(digest) is None:
            return None
        directory = self._root / f"{kind}s"
        payload = _read_optional(directory / f"{digest}.json")
        if payload is None:
            return None
        signature = _read_optional(directory / f"{digest}.sig")
        return SignedArtifact(payload=payload, signature=signature or b"")


@dataclass(frozen=True, slots=True)
class VerifiedRelease:
    """The image digests and capability maximums of a signature-verified Release manifest."""

    digest: str
    artifact_digests: frozenset[str]
    capability_maximums: Mapping[str, CapabilityMode]

    def maximum_envelope(self, local: LifecycleEffectEnvelope) -> LifecycleEffectEnvelope:
        """Return the maximum envelope derived from local hard policy and this signed Release.

        A capability is allowed only when both name it, at the lower of the two modes
        (ADR-0003 A16). Entities, regions, destructive changes, and duration stay local policy.
        """

        modes = {
            capability: min(mode, self.capability_maximums[capability], key=_AUTHORITY.index)
            for capability, mode in local.capability_modes.items()
            if capability in self.capability_maximums
        }
        return replace(local, capability_modes=modes)


def verify_release(
    plan: LifecyclePlan, store: ArtifactStore, verify_signature: ArtifactVerifier
) -> VerifiedRelease:
    """Verify the Plan's target Release or raise ``InputRejectedError``."""

    document = _verified_document("release", plan.target_release_digest, store, verify_signature)
    if document.get("schema_version") != LIFECYCLE_RELEASE_SCHEMA:
        raise InputRejectedError("release", InputProblem.SCHEMA_UNSUPPORTED)
    match document.get("capabilities"):
        case dict(capabilities) if capabilities:
            pass
        case _:
            raise InputRejectedError("release", InputProblem.MALFORMED)
    maximums: dict[str, CapabilityMode] = {}
    for capability, record in capabilities.items():
        match record:
            case {"maximum_mode": "shadow" | "enforce" as mode}:
                maximums[capability] = mode
            case _:
                raise InputRejectedError("release", InputProblem.MALFORMED)
    artifacts: set[str] = set()
    for section in _IMAGE_SECTIONS:
        records = document.get(section)
        if not isinstance(records, dict) or not records:
            raise InputRejectedError("release", InputProblem.MALFORMED)
        for record in records.values():
            match record:
                case {"image_digest": str(digest)} if _IMAGE_DIGEST.fullmatch(digest):
                    artifacts.add(digest)
                case _:
                    raise InputRejectedError("release", InputProblem.MALFORMED)
    return VerifiedRelease(
        digest=plan.target_release_digest,
        artifact_digests=frozenset(artifacts),
        capability_maximums=maximums,
    )


def verify_configuration(
    plan: LifecyclePlan, store: ArtifactStore, verify_signature: ArtifactVerifier
) -> None:
    """Verify the Plan's configuration package or raise ``InputRejectedError``."""

    document = _verified_document(
        "configuration", plan.configuration_revision_digest, store, verify_signature
    )
    try:
        validate_configuration_package_for_signing(document)
    except ConfigurationValidationError as error:
        raise InputRejectedError("configuration", InputProblem.LITERAL_SECRET) from error


def _verified_document(
    kind: InputKind,
    expected_digest: str,
    store: ArtifactStore,
    verify_signature: ArtifactVerifier,
) -> dict[str, object]:
    try:
        artifact = store.load(kind, expected_digest)
    except (OSError, ValueError) as error:
        raise InputRejectedError(kind, InputProblem.UNREADABLE) from error
    if artifact is None:
        raise InputRejectedError(kind, InputProblem.UNAVAILABLE)
    if not artifact.signature:
        raise InputRejectedError(kind, InputProblem.SIGNATURE_MISSING)
    try:
        verified = verify_signature(artifact.payload, artifact.signature)
    except (TypeError, ValueError):
        verified = False
    if verified is not True:
        raise InputRejectedError(kind, InputProblem.SIGNATURE_INVALID)
    try:
        document = load_json(artifact.payload, label=kind)
    except ValueError as error:
        raise InputRejectedError(kind, InputProblem.MALFORMED) from error
    if not isinstance(document, dict):
        raise InputRejectedError(kind, InputProblem.MALFORMED)
    if canonical_digest(document) != expected_digest:
        raise InputRejectedError(kind, InputProblem.DIGEST_MISMATCH)
    return document


def _read_optional(path: Path) -> bytes | None:
    try:
        return read_limited(path, limit=MAX_INPUT_BYTES, label=path.name)
    except FileNotFoundError:
        return None
