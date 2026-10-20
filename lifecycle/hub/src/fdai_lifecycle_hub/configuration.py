"""Explicit in-memory signed configuration input, not enrollment or durable import."""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai_deployment_cli.lifecycle_configuration_entities import InstallationLayerResolution
from fdai_deployment_cli.lifecycle_configuration_package import (
    SignedConfigurationPackage,
    verify_installation_configuration_package,
)
from fdai_deployment_cli.runtime_release import RuntimeRelease


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfigurationRevisionCandidate:
    """Caller supplies independent key bindings and the retained complete accepted chain.

    This transient input is intentionally not an enrollment/API/ORM record. Passing it cannot
    register trust or make an unmanaged Entity eligible for planning.
    """

    package: SignedConfigurationPackage
    configuration_key: Ed25519PublicKey
    installation_key_digest: str
    sealed_keys: frozenset[str]
    expected_predecessor: str | None
    history: tuple[SignedConfigurationPackage, ...] = ()

    def resolve(
        self, release_id: str, release: RuntimeRelease, entity_ids: frozenset[str]
    ) -> InstallationLayerResolution:
        """Verify against the exact catalog schema and existing managed Entity selection."""
        head = self.history[-1].digest if self.history else None
        if head != self.expected_predecessor:
            raise ValueError("configuration history does not match the retained head")
        schema = release.configuration_schema
        if schema is None or schema.release_version != release_id:
            raise ValueError("Release has no matching configuration schema capability")
        return verify_installation_configuration_package(
            self.package,
            configuration_key=self.configuration_key,
            installation_key_digest=self.installation_key_digest,
            configuration_schema=schema.to_mapping(),
            sealed_keys=self.sealed_keys,
            entity_ids=entity_ids,
            release_version=release_id,
            release_digest=release.digest,
            history=self.history,
        )
