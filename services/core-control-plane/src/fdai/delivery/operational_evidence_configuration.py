"""Deployment configuration for operational evidence issuance and admission.

Upstream ships only the reviewed trust registry with logical identifiers. Deployment supplies
the pins, the case-scope grant registry, the anchor-to-principal binding, the proof-store
connection, and the verifier endpoint; none of those values ever enters the repository, and no
value read here is echoed back by the Settings projection.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fdai_service_contracts.venue import (
    ExecutionVenue,
    ExecutionVenueError,
    resolve_execution_venue,
)

from fdai.core.operational_evidence.grant_registry_loader import load_grant_registry
from fdai.core.operational_evidence.registry_json import RegistryUnavailableError
from fdai.core.operational_evidence.revision_history import RegistryHistory, RegistryRevision
from fdai.core.operational_evidence.trust_registry import (
    DeploymentAnchors,
)
from fdai.core.operational_evidence.trust_registry_loader import (
    load_deployment_anchors,
    load_trust_registry,
)

ENABLED_ENV = "FDAI_OPERATIONAL_EVIDENCE_ENABLED"
TRUST_PATH_ENV = "FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PATH"
TRUST_PIN_ENV = "FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PIN"
GRANT_PATH_ENV = "FDAI_OPERATIONAL_EVIDENCE_GRANT_REGISTRY_PATH"
GRANT_PIN_ENV = "FDAI_OPERATIONAL_EVIDENCE_GRANT_REGISTRY_PIN"
HISTORY_ENV = "FDAI_OPERATIONAL_EVIDENCE_REGISTRY_HISTORY_JSON"
ANCHORS_ENV = "FDAI_OPERATIONAL_EVIDENCE_ANCHORS_JSON"
VERIFIER_URL_ENV = "FDAI_OPERATIONAL_EVIDENCE_VERIFIER_URL"
READER_DSN_ENV = "FDAI_OPERATIONAL_EVIDENCE_READER_DSN"
READER_ROLE_ENV = "FDAI_OPERATIONAL_EVIDENCE_READER_ROLE"
VERIFIER_DSN_ENV = "FDAI_OPERATIONAL_EVIDENCE_VERIFIER_DSN"
EXECUTOR_PRINCIPALS_ENV = "FDAI_OPERATIONAL_EVIDENCE_EXECUTOR_PRINCIPALS_JSON"
WRITER_MEMBERS_ENV = "FDAI_OPERATIONAL_EVIDENCE_WRITER_MEMBERS_JSON"
DEFAULT_TRUST_REGISTRY = "config/operational-evidence-trust-registry.json"
VERIFIER_ID = "operational-evidence-verifier"
VERIFIER_VERSION = "1.0.0"
PRODUCER_ID = "core-control-plane"
PRODUCER_VERSION = "1.0.0"
_MAX_HISTORY = 16


class OperationalEvidenceConfigurationError(ValueError):
    """Deployment configuration is missing or malformed; every purpose stays unavailable."""


@dataclass(frozen=True, slots=True)
class OperationalEvidenceSettings:
    """Parsed prerequisites; presence alone never makes a purpose available."""

    enabled: bool
    trust_path: str
    trust_pin: str
    grant_path: str
    grant_pin: str
    history_json: str
    anchors_json: str
    verifier_url: str
    reader_dsn: str
    reader_role: str
    verifier_dsn: str
    executor_principals_json: str
    writer_members_json: str
    execution_venue: ExecutionVenue | None

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> OperationalEvidenceSettings:
        """Read deployment values; the venue comes only from the authoritative resolver."""

        try:
            venue: ExecutionVenue | None = resolve_execution_venue(env)
        except ExecutionVenueError:
            venue = None
        return cls(
            enabled=env.get(ENABLED_ENV, "").strip() == "1",
            trust_path=env.get(TRUST_PATH_ENV, "").strip() or DEFAULT_TRUST_REGISTRY,
            trust_pin=env.get(TRUST_PIN_ENV, "").strip(),
            grant_path=env.get(GRANT_PATH_ENV, "").strip(),
            grant_pin=env.get(GRANT_PIN_ENV, "").strip(),
            history_json=env.get(HISTORY_ENV, "").strip(),
            anchors_json=env.get(ANCHORS_ENV, "").strip(),
            verifier_url=env.get(VERIFIER_URL_ENV, "").strip(),
            reader_dsn=env.get(READER_DSN_ENV, "").strip() or env.get("FDAI_STATE_STORE_DSN", ""),
            reader_role=env.get(READER_ROLE_ENV, "").strip() or "fdai_core",
            verifier_dsn=env.get(VERIFIER_DSN_ENV, "").strip(),
            executor_principals_json=env.get(EXECUTOR_PRINCIPALS_ENV, "").strip(),
            writer_members_json=env.get(WRITER_MEMBERS_ENV, "").strip(),
            execution_venue=venue,
        )

    def prerequisites(self) -> dict[str, bool]:
        """Return which deployment inputs are present, without echoing any value."""

        return {
            TRUST_PIN_ENV: bool(self.trust_pin),
            GRANT_PATH_ENV: bool(self.grant_path),
            GRANT_PIN_ENV: bool(self.grant_pin),
            ANCHORS_ENV: bool(self.anchors_json),
            VERIFIER_URL_ENV: bool(self.verifier_url),
            READER_DSN_ENV: bool(self.reader_dsn.strip()),
        }


def load_registry_history(settings: OperationalEvidenceSettings, *, root: Path) -> RegistryHistory:
    """Load every pinned revision oldest first; the configured pins are the current revision."""

    if not settings.trust_pin or not settings.grant_path or not settings.grant_pin:
        raise RegistryUnavailableError("operational evidence registry pins are not configured")
    revisions: list[tuple[str, str, str, str]] = []
    if settings.history_json:
        try:
            raw = json.loads(settings.history_json)
        except json.JSONDecodeError as exc:
            raise RegistryUnavailableError("registry history is not valid JSON") from exc
        if not isinstance(raw, list) or len(raw) > _MAX_HISTORY:
            raise RegistryUnavailableError("registry history MUST be a bounded array")
        for item in raw:
            if not isinstance(item, dict) or set(item) != {
                "trust_path",
                "trust_pin",
                "grant_path",
                "grant_pin",
            }:
                raise RegistryUnavailableError("registry history entry is malformed")
            revisions.append(
                (
                    str(item["trust_path"]),
                    str(item["trust_pin"]),
                    str(item["grant_path"]),
                    str(item["grant_pin"]),
                )
            )
    revisions.append(
        (settings.trust_path, settings.trust_pin, settings.grant_path, settings.grant_pin)
    )
    return RegistryHistory(
        tuple(
            RegistryRevision(
                trust=load_trust_registry(_read(root, trust_path), expected_pin=trust_pin),
                grants=load_grant_registry(_read(root, grant_path), expected_pin=grant_pin),
            )
            for trust_path, trust_pin, grant_path, grant_pin in revisions
        )
    )


def load_anchors(settings: OperationalEvidenceSettings) -> DeploymentAnchors:
    """Parse the deployment anchor binding or refuse every purpose."""

    if not settings.anchors_json:
        raise RegistryUnavailableError("operational evidence anchors are not configured")
    if settings.execution_venue is None:
        raise RegistryUnavailableError("the execution venue is invalid")
    return load_deployment_anchors(settings.anchors_json, execution_venue=settings.execution_venue)


def string_list(raw: str, *, label: str) -> tuple[str, ...]:
    """Parse an optional JSON array of bounded principal names."""

    if not raw:
        return ()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OperationalEvidenceConfigurationError(f"{label} is not valid JSON") from exc
    if (
        not isinstance(value, list)
        or len(value) > 64
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise OperationalEvidenceConfigurationError(f"{label} MUST be an array of strings")
    return tuple(sorted(set(value)))


def _read(root: Path, reference: str) -> bytes:
    path = Path(reference)
    if not path.is_absolute():
        path = root / path
    if path.is_symlink() or not path.is_file():
        raise RegistryUnavailableError("operational evidence registry MUST be a regular file")
    return path.read_bytes()


__all__ = [
    "ANCHORS_ENV",
    "DEFAULT_TRUST_REGISTRY",
    "ENABLED_ENV",
    "PRODUCER_ID",
    "PRODUCER_VERSION",
    "VERIFIER_ID",
    "VERIFIER_VERSION",
    "OperationalEvidenceConfigurationError",
    "OperationalEvidenceSettings",
    "load_anchors",
    "load_registry_history",
    "string_list",
]
