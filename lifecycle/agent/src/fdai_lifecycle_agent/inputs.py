"""Signed Release and configuration package inputs for one admitted Plan.

Both inputs are verified before any change is computed (ADR-0003 A15). The signature covers the
exact file bytes. The digest that the Plan names is the SHA-256 of the canonical JSON of the
document, as the Hub computes it (``RuntimeRelease.digest`` and ``canonical_digest`` of the
configuration). A missing or failed signature, a digest that differs from the Plan, or a malformed
document rejects the Plan with a stable reason code. Both signed inputs can only narrow the locally
derived maximum envelope.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, cast, get_args

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_configuration import (
    ConfigurationValidationError,
    resolve_configuration_layers,
    validate_configuration_package_for_signing,
)
from fdai_deployment_cli.lifecycle_plan import (
    CapabilityMode,
    LifecycleEffectEnvelope,
    LifecyclePlan,
)
from fdai_deployment_cli.runtime_release import RuntimeReleaseError, parse_runtime_release_manifest

from fdai_lifecycle_agent.signatures import ArtifactVerifier
from fdai_lifecycle_agent.strict_json import load_json, read_limited

LIFECYCLE_RELEASE_SCHEMA = "fdai.runtime-release.v3"
MAX_INPUT_BYTES = 1024 * 1024
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_IMAGE_SECTIONS = ("services", "sidecars", "installation_agents")
_CONFIGURATION_KEYS = frozenset({"schema", "environment", "entity_overrides"})
# The Environment Config key that names the installation's Azure region (data residency).
REGION_KEY = "region"
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
    OVERRIDE_MISSING = "override_missing"
    COMPONENT_MISSING = "component_missing"


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
    """A signature-verified, fully validated ``fdai.runtime-release.v3`` manifest."""

    digest: str
    component_images: Mapping[str, str]
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

    def entity_images(
        self, entity_components: Mapping[str, frozenset[str]], entity_ids: frozenset[str]
    ) -> dict[str, frozenset[str]]:
        """Return the images each Entity runs in this Release, from its local component list.

        Raises ``InputRejectedError`` when the Release lacks a component an Entity runs.
        """

        try:
            return {
                entity_id: frozenset(
                    self.component_images[component] for component in entity_components[entity_id]
                )
                for entity_id in entity_ids
            }
        except KeyError as error:
            raise InputRejectedError("release", InputProblem.COMPONENT_MISSING) from error


@dataclass(frozen=True, slots=True)
class VerifiedConfiguration:
    """A signature-verified configuration package, resolved for the target Release."""

    digest: str
    values: Mapping[str, object]

    def narrow(self, envelope: LifecycleEffectEnvelope) -> LifecycleEffectEnvelope:
        """Narrow ``envelope`` by the configured Azure region. Configuration never widens it."""

        match self.values.get(REGION_KEY):
            case str(region):
                return replace(envelope, regions=envelope.regions & {region})
        return envelope


def verify_release(
    plan: LifecyclePlan, store: ArtifactStore, verify_signature: ArtifactVerifier
) -> VerifiedRelease:
    """Verify the Plan's target Release or raise ``InputRejectedError``.

    The manifest passes the same full validation that the deployment CLI and the Hub apply.
    """

    payload = _verified_payload("release", plan.target_release_digest, store, verify_signature)
    try:
        release = parse_runtime_release_manifest(payload)
    except RuntimeReleaseError as error:
        raise InputRejectedError("release", InputProblem.MALFORMED) from error
    if release.schema_version != LIFECYCLE_RELEASE_SCHEMA:
        raise InputRejectedError("release", InputProblem.SCHEMA_UNSUPPORTED)
    if release.digest != plan.target_release_digest:
        raise InputRejectedError("release", InputProblem.DIGEST_MISMATCH)
    return VerifiedRelease(
        digest=release.digest,
        component_images=_component_images(release.to_mapping()),
        # The manifest parser restricted every maximum to a CapabilityMode value.
        capability_maximums=cast(dict[str, CapabilityMode], release.capability_maximums),
    )


def verify_configuration(
    plan: LifecyclePlan, store: ArtifactStore, verify_signature: ArtifactVerifier
) -> VerifiedConfiguration:
    """Verify the Plan's configuration package and resolve it for the target Release.

    Raises ``InputRejectedError``. A package without an override block for the target Release
    isn't deployable (``configuration_override_missing``).
    """

    payload = _verified_payload(
        "configuration", plan.configuration_revision_digest, store, verify_signature
    )
    try:
        document = load_json(payload, label="configuration")
    except ValueError as error:
        raise InputRejectedError("configuration", InputProblem.MALFORMED) from error
    if not isinstance(document, dict) or set(document) != _CONFIGURATION_KEYS:
        raise InputRejectedError("configuration", InputProblem.MALFORMED)
    if canonical_digest(document) != plan.configuration_revision_digest:
        raise InputRejectedError("configuration", InputProblem.DIGEST_MISMATCH)
    try:
        validate_configuration_package_for_signing(document)
    except ConfigurationValidationError as error:
        raise InputRejectedError("configuration", InputProblem.LITERAL_SECRET) from error
    match document:
        case {
            "schema": dict(schema),
            "environment": dict(environment),
            "entity_overrides": list(overrides),
        }:
            pass
        case _:
            raise InputRejectedError("configuration", InputProblem.MALFORMED)
    try:
        resolution = resolve_configuration_layers(
            release_version=plan.target_release_id,
            configuration_schema=schema,
            environment_config=environment,
            entity_overrides=tuple(overrides),
        )
    except ConfigurationValidationError as error:
        problem = (
            InputProblem.OVERRIDE_MISSING
            if error.code == "missing_matching_override_block"
            else InputProblem.MALFORMED
        )
        raise InputRejectedError("configuration", problem) from error
    return VerifiedConfiguration(
        digest=plan.configuration_revision_digest, values=resolution.values
    )


def _verified_payload(
    kind: InputKind,
    expected_digest: str,
    store: ArtifactStore,
    verify_signature: ArtifactVerifier,
) -> bytes:
    """Load the artifact and verify its signature over the exact bytes; nothing is parsed yet."""

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
    return artifact.payload


def _component_images(catalog: Mapping[str, object]) -> dict[str, str]:
    images: dict[str, str] = {}
    for section in _IMAGE_SECTIONS:
        match catalog.get(section):
            case dict(records):
                for name, record in records.items():
                    match record:
                        case {"image_digest": str(digest)}:
                            images[str(name)] = digest
    return images


def _read_optional(path: Path) -> bytes | None:
    try:
        return read_limited(path, limit=MAX_INPUT_BYTES, label=path.name)
    except FileNotFoundError:
        return None
