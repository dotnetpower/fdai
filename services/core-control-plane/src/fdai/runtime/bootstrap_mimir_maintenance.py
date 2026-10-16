"""Bind reviewed Mimir maintenance evidence without inventing source authority."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fdai.delivery.mimir_maintenance_evidence import ImmutableMimirMaintenanceEvidence

_PATH_ENV = "FDAI_MIMIR_MAINTENANCE_EVIDENCE_PATH"
_DIGEST_ENV = "FDAI_MIMIR_MAINTENANCE_EVIDENCE_SHA256"
_SOURCE_REVISION_ENV = "FDAI_SOURCE_REVISION"


def build_mimir_maintenance_source(
    environment: Mapping[str, str],
) -> ImmutableMimirMaintenanceEvidence | None:
    """Return one complete reviewed source or keep all maintenance ports unbound."""

    path_value = environment.get(_PATH_ENV, "").strip()
    digest = environment.get(_DIGEST_ENV, "").strip()
    if not path_value and not digest:
        return None
    if not path_value or not digest:
        raise RuntimeError("Mimir maintenance evidence configuration is incomplete")
    source_revision = environment.get(_SOURCE_REVISION_ENV, "").strip()
    if not source_revision:
        raise RuntimeError("Mimir maintenance evidence requires FDAI_SOURCE_REVISION")
    path = Path(path_value)
    if not path.is_absolute():
        raise RuntimeError("Mimir maintenance evidence path MUST be absolute")
    try:
        source = ImmutableMimirMaintenanceEvidence.load(path, expected_digest=digest)
    except ValueError as exc:
        raise RuntimeError("Mimir maintenance evidence is invalid") from exc
    if source.source_revision != source_revision:
        raise RuntimeError("Mimir maintenance evidence source revision differs")
    return source


__all__ = ["build_mimir_maintenance_source"]
