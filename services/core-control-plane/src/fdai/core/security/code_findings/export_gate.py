"""Export gate: a pack leaves FDAI only for an approved coding-agent provider.

A remediation pack carries undisclosed vulnerability detail. When a developer runs it with a
hosted coding agent, that detail reaches the agent provider's service. The deployment therefore
lists which providers are approved, under which data-residency, training, and retention terms,
and which pack modes each may receive. Export fails closed when the provider is absent, its
approval has expired, or the requested mode is not allowed.

The provider list is deployment configuration owned by the installation, not upstream data.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from fdai.core.security.code_findings.pack import PackMode

_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9.-]{1,63}$")


class ExportDeniedError(PermissionError):
    """Raised when a pack may not be exported to the requested provider and mode."""


@dataclass(frozen=True, slots=True)
class ApprovedAgentProvider:
    provider_id: str
    display_name: str
    modes: frozenset[PackMode]
    data_residency: str
    training_use: str
    retention_days: int
    approved_until: date

    def __post_init__(self) -> None:
        if _PROVIDER_ID.fullmatch(self.provider_id) is None:
            raise ValueError("provider_id must be lowercase ASCII")
        if self.training_use != "none":
            raise ValueError("an approved provider must not train on exported content")
        if not self.modes:
            raise ValueError("an approved provider needs at least one pack mode")
        if not 0 <= self.retention_days <= 365:
            raise ValueError("retention_days must be within 0-365")


@dataclass(frozen=True, slots=True)
class AgentProviderPolicy:
    version: str
    providers: tuple[ApprovedAgentProvider, ...]

    @classmethod
    def from_mapping(cls, document: Mapping[str, object]) -> AgentProviderPolicy:
        """Build a policy from parsed configuration; unknown keys or bad values raise."""
        allowed = {"schema_version", "version", "providers"}
        if set(document) - allowed or document.get("schema_version") != 1:
            raise ValueError("agent provider policy must use schema_version 1 and known keys")
        raw = document.get("providers") or []
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ValueError("providers must be a list")
        providers: list[ApprovedAgentProvider] = []
        for entry in raw:
            if not isinstance(entry, Mapping):
                raise ValueError("each provider must be a mapping")
            modes = entry.get("modes")
            if not isinstance(modes, Sequence) or isinstance(modes, (str, bytes)):
                raise ValueError("provider modes must be a list")
            providers.append(
                ApprovedAgentProvider(
                    provider_id=str(entry["id"]),
                    display_name=str(entry["display_name"]),
                    modes=frozenset(PackMode(str(mode)) for mode in modes),
                    data_residency=str(entry["data_residency"]),
                    training_use=str(entry["training_use"]),
                    retention_days=int(str(entry["retention_days"])),
                    approved_until=date.fromisoformat(str(entry["approved_until"])),
                )
            )
        ids = [provider.provider_id for provider in providers]
        if len(ids) != len(set(ids)):
            raise ValueError("provider ids must be unique")
        return cls(version=str(document.get("version", "")), providers=tuple(providers))


def authorize_export(
    policy: AgentProviderPolicy, provider_id: str, mode: PackMode, today: date
) -> ApprovedAgentProvider:
    """Return the approved provider for this export or raise :class:`ExportDeniedError`."""
    provider = next((p for p in policy.providers if p.provider_id == provider_id), None)
    if provider is None:
        raise ExportDeniedError(f"provider {provider_id!r} is not approved for remediation packs")
    if today > provider.approved_until:
        raise ExportDeniedError(f"provider {provider_id!r} approval expired")
    if mode not in provider.modes:
        allowed = ", ".join(sorted(m.value for m in provider.modes))
        raise ExportDeniedError(f"provider {provider_id!r} may receive only: {allowed}")
    return provider


__all__ = [
    "AgentProviderPolicy",
    "ApprovedAgentProvider",
    "ExportDeniedError",
    "authorize_export",
]
