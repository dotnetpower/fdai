"""Explicit in-memory signed configuration input, not enrollment or durable import."""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai_deployment_cli.lifecycle_configuration_entities import InstallationLayerResolution
from fdai_deployment_cli.lifecycle_configuration_package import (
    ConfigurationHistoryBinding,
    SignedConfigurationPackage,
    verify_installation_configuration_package,
)
from fdai_deployment_cli.lifecycle_release import LifecycleRelease


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfigurationRevisionCandidate:
    """Caller supplies independent key bindings and the retained complete accepted chain.

    This transient input is intentionally not an enrollment/API/ORM record. Passing it cannot
    register trust or make an unmanaged Entity eligible for planning.
    """

    package: SignedConfigurationPackage
    installation_id: str
    entity_bindings: tuple[tuple[str, str], ...]
    configuration_key: Ed25519PublicKey
    installation_key_digest: str
    sealed_keys: frozenset[str]
    expected_predecessor: str | None
    history: tuple[SignedConfigurationPackage, ...] = ()
    history_bindings: tuple[ConfigurationHistoryBinding, ...] | None = None

    def resolve(
        self,
        release_id: str,
        release: LifecycleRelease,
        entity_ids: frozenset[str],
        *,
        installation_id: str,
    ) -> InstallationLayerResolution:
        """Verify against the exact catalog schema and existing managed Entity selection."""
        bindings = dict(self.entity_bindings)
        if (
            not installation_id
            or self.installation_id != installation_id
            or len(bindings) != len(self.entity_bindings)
            or frozenset(bindings) != entity_ids
            or len(set(bindings.values())) != len(bindings)
        ):
            raise ValueError("configuration Entity bindings do not match the managed installation")
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
            entity_ids=frozenset(bindings.values()),
            release_version=release_id,
            release_digest=release.digest,
            history=self.history,
            history_bindings=self.history_bindings,
        )
