"""Immutable bounded values shared by generic ontology query nodes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from fdai.shared.providers.ontology_instance import normalize_json_value

_MAX_ROWS = 1_000
_MAX_ROW_BYTES = 65_536
_MAX_TABLE_BYTES = 8_388_608


@dataclass(frozen=True, slots=True)
class QueryRow:
    """One stable row whose payload is canonical bounded JSON."""

    row_id: str
    values_json: str

    def __post_init__(self) -> None:
        if not self.row_id or len(self.row_id) > 512:
            raise ValueError("query row id MUST contain between 1 and 512 characters")
        values = _parse_values(self.values_json)
        if _canonical_json(values) != self.values_json:
            raise ValueError("query row values_json MUST be canonical JSON")
        if len(self.values_json.encode("utf-8")) > _MAX_ROW_BYTES:
            raise ValueError(f"query row exceeds {_MAX_ROW_BYTES} bytes")

    @classmethod
    def from_values(cls, row_id: str, values: object) -> QueryRow:
        """Normalize and freeze one JSON object payload."""

        normalized = normalize_json_value(values, path=f"query_row.{row_id}")
        if not isinstance(normalized, dict):
            raise ValueError("query row values MUST be a JSON object")
        return cls(row_id=row_id, values_json=_canonical_json(normalized))

    @property
    def values(self) -> dict[str, Any]:
        """Return a fresh mutable copy of the canonical payload."""

        return _parse_values(self.values_json)


@dataclass(frozen=True, slots=True)
class QueryTable:
    """One bounded row set with explicit completeness and content identity."""

    rows: tuple[QueryRow, ...]
    complete: bool
    truncation_reason: str | None = None

    def __post_init__(self) -> None:
        if len(self.rows) > _MAX_ROWS:
            raise ValueError(f"query table exceeds {_MAX_ROWS} rows")
        row_ids = [row.row_id for row in self.rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("query table row ids MUST be unique")
        if self.complete == (self.truncation_reason is not None):
            raise ValueError("query table completeness and truncation reason are inconsistent")
        if len(self.canonical_json().encode("utf-8")) > _MAX_TABLE_BYTES:
            raise ValueError(f"query table exceeds {_MAX_TABLE_BYTES} bytes")

    def canonical_json(self) -> str:
        """Return replay-stable table content without execution metadata."""

        return _canonical_json(
            {
                "rows": [{"row_id": row.row_id, "values": row.values} for row in self.rows],
                "complete": self.complete,
                "truncation_reason": self.truncation_reason,
            }
        )

    @property
    def digest(self) -> str:
        """Return the table's content-addressed replay identity."""

        return "sha256:" + hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def combine_incompleteness(tables: tuple[QueryTable, ...]) -> str | None:
    """Return one deterministic reason when any source table is incomplete."""

    reasons = sorted(
        {table.truncation_reason or "source_incomplete" for table in tables if not table.complete}
    )
    return "+".join(reasons) if reasons else None


def _parse_values(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("query row values_json MUST contain JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("query row values_json MUST contain an object")
    return parsed


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = ["QueryRow", "QueryTable", "combine_incompleteness"]
