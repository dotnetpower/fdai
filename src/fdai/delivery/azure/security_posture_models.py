"""Typed supplemental Azure evidence for security posture analysis."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AzureCveEvidence:
    """One advisory match produced by a version-aware collector."""

    cve_id: str
    applicability: str
    patch_status: str
    source_url: str
    managed_service_note: str = ""


@dataclass(frozen=True, slots=True)
class AzureResourceSecurityEvidence:
    """Supplemental reads not present in a Resource Graph resource row."""

    server_parameters: Mapping[str, str] = field(default_factory=dict)
    diagnostic_settings_enabled: bool | None = None
    defender_enabled: bool | None = None
    cves: tuple[AzureCveEvidence, ...] = ()


__all__ = ["AzureCveEvidence", "AzureResourceSecurityEvidence"]
