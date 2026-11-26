"""Runtime manifest integrity for the MSCP operational profile.

MSCP provenance: Level 3 identity continuity. FDAI transforms the concept
into deterministic integrity checks over versioned runtime components rather
than modeling an agent persona or mutable identity vector.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.mscp_profile.profile import DEFAULT_PROFILE


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class RuntimeComponent:
    """One pre-hashed, secret-free component in a runtime safety manifest."""

    name: str
    revision: str
    digest: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name MUST be non-empty")
        if not self.revision.strip():
            raise ValueError("revision MUST be non-empty")
        if not _is_sha256(self.digest):
            raise ValueError("digest MUST be a lowercase SHA-256 value")


@dataclass(frozen=True, slots=True)
class RuntimeSafetyManifest:
    profile_id: str
    components: tuple[RuntimeComponent, ...]

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id MUST be non-empty")
        if not self.components:
            raise ValueError("components MUST contain at least one runtime component")
        names = [component.name for component in self.components]
        if len(names) != len(set(names)):
            raise ValueError("runtime component names MUST be unique")

    def digest(self) -> str:
        """Hash a canonical projection without reading component contents."""

        payload = {
            "components": [
                {
                    "digest": component.digest,
                    "name": component.name,
                    "revision": component.revision,
                }
                for component in sorted(self.components, key=lambda item: item.name)
            ],
            "profile_id": self.profile_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class RuntimeIntegrityStatus(StrEnum):
    VERIFIED = "verified"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class RuntimeIntegrityResult:
    status: RuntimeIntegrityStatus
    changed_components: tuple[str, ...] = ()
    profile_mismatch: bool = False


def verify_runtime_integrity(
    expected: RuntimeSafetyManifest,
    observed: RuntimeSafetyManifest,
) -> RuntimeIntegrityResult:
    """Compare two manifests and hold when profile or components drift."""

    expected_by_name = {component.name: component for component in expected.components}
    observed_by_name = {component.name: component for component in observed.components}
    changed = tuple(
        sorted(
            name
            for name in expected_by_name.keys() | observed_by_name.keys()
            if expected_by_name.get(name) != observed_by_name.get(name)
        )
    )
    profile_mismatch = expected.profile_id != observed.profile_id
    if profile_mismatch or changed:
        return RuntimeIntegrityResult(
            RuntimeIntegrityStatus.HOLD,
            changed_components=changed,
            profile_mismatch=profile_mismatch,
        )
    return RuntimeIntegrityResult(RuntimeIntegrityStatus.VERIFIED)


def default_runtime_manifest(
    components: tuple[RuntimeComponent, ...],
) -> RuntimeSafetyManifest:
    """Build a manifest bound to the active MSCP operational profile."""

    return RuntimeSafetyManifest(DEFAULT_PROFILE.profile_id, components)


__all__ = [
    "RuntimeComponent",
    "RuntimeIntegrityResult",
    "RuntimeIntegrityStatus",
    "RuntimeSafetyManifest",
    "default_runtime_manifest",
    "verify_runtime_integrity",
]
