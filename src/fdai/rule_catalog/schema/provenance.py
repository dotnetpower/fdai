"""Governance-artifact provenance - who created a catalog artifact and when.

Every governance catalog-as-code artifact (rule-set, assignment, exemption,
override) records provenance so a change is attributable and replayable
(rule-governance.md "YAML Shapes"). This is the shared, CSP-neutral value object
each artifact carries; the loaders build it from the artifact's ``provenance``
block, and future artifact kinds reuse it unchanged - provenance is part of the
extensible governance-artifact envelope, not per-artifact bespoke.

Pure and I/O-free.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Provenance:
    """Attribution for a governance artifact: when it was created, by whom, and
    optionally the upstream source it was derived from.

    ``created_at`` MUST be timezone-aware (RFC 3339 / ISO 8601). ``source`` is
    optional and left open for extension (e.g. an upstream catalog id or a
    collection-pipeline snapshot reference).
    """

    created_at: datetime
    created_by: str
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.created_by.strip():
            raise ValueError("Provenance.created_by MUST be non-empty")
        if self.created_at.tzinfo is None:
            raise ValueError("Provenance.created_at MUST be timezone-aware (RFC 3339)")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Provenance:
        """Build from a parsed ``provenance`` mapping.

        ``created_at`` may arrive as an RFC 3339 string (JSON) or as an already
        parsed :class:`datetime` (a YAML timestamp scalar); both are accepted. A
        naive or malformed timestamp raises :class:`ValueError`, which the load
        boundary aggregates into its issue list.
        """
        raw_created_at = raw["created_at"]
        if isinstance(raw_created_at, datetime):
            created_at = raw_created_at
        else:
            try:
                created_at = datetime.fromisoformat(str(raw_created_at))
            except ValueError as exc:
                raise ValueError(
                    f"Provenance.created_at is not a valid RFC 3339 timestamp: {raw_created_at!r}"
                ) from exc
        source = raw.get("source")
        return cls(
            created_at=created_at,
            created_by=str(raw["created_by"]),
            source=str(source) if source is not None else None,
        )


__all__ = ["Provenance"]
