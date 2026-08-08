"""Immutable registry for versioned frozen configuration baselines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai.core.detection.configuration_drift_models import FrozenConfigurationBaseline


class ConfigurationBaselineStatus(StrEnum):
    """Deployment-owned lifecycle state for one frozen baseline version."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class ConfigurationBaselineNotFoundError(KeyError):
    """The configured registry does not contain the requested server-owned key."""


@dataclass(frozen=True, slots=True)
class RegisteredConfigurationBaseline:
    """One immutable baseline and its deployment-owned lifecycle state."""

    baseline: FrozenConfigurationBaseline
    status: ConfigurationBaselineStatus

    @property
    def key(self) -> tuple[str, str]:
        return (self.baseline.scope, self.baseline.version)


class ConfigurationBaselineRegistry:
    """Validate and query a fixed set of baseline versions without mutation APIs."""

    def __init__(self, records: tuple[RegisteredConfigurationBaseline, ...]) -> None:
        by_key = {record.key: record for record in records}
        if len(by_key) != len(records):
            raise ValueError("configuration baseline registry keys MUST be unique")
        active_scopes: set[str] = set()
        for record in records:
            if record.status is not ConfigurationBaselineStatus.ACTIVE:
                continue
            scope = record.baseline.scope
            if scope in active_scopes:
                raise ValueError(
                    "configuration baseline registry allows one active version per scope"
                )
            active_scopes.add(scope)
        self._records = tuple(sorted(records, key=lambda record: record.key))
        self._by_key = by_key

    def list(self, *, scope: str | None = None) -> tuple[RegisteredConfigurationBaseline, ...]:
        """Return all records, optionally restricted to one exact scope."""

        if scope is None:
            return self._records
        return tuple(record for record in self._records if record.baseline.scope == scope)

    def get(self, *, scope: str, version: str) -> RegisteredConfigurationBaseline:
        """Return one exact server-owned registry entry."""

        try:
            return self._by_key[(scope, version)]
        except KeyError as exc:
            raise ConfigurationBaselineNotFoundError((scope, version)) from exc

    def active(self, *, scope: str) -> RegisteredConfigurationBaseline:
        """Return the single active baseline for a configured scope."""

        matches = tuple(
            record
            for record in self._records
            if record.baseline.scope == scope
            and record.status is ConfigurationBaselineStatus.ACTIVE
        )
        if not matches:
            raise ConfigurationBaselineNotFoundError((scope, "active"))
        return matches[0]


@dataclass(frozen=True, slots=True)
class RegistryConfigurationBaselineSource:
    """Load an active or exact version from a server-owned immutable registry."""

    registry: ConfigurationBaselineRegistry
    scope: str
    version: str | None = None

    async def load(self) -> FrozenConfigurationBaseline:
        record = (
            self.registry.active(scope=self.scope)
            if self.version is None
            else self.registry.get(scope=self.scope, version=self.version)
        )
        return record.baseline


__all__ = [
    "ConfigurationBaselineNotFoundError",
    "ConfigurationBaselineRegistry",
    "ConfigurationBaselineStatus",
    "RegisteredConfigurationBaseline",
    "RegistryConfigurationBaselineSource",
]
