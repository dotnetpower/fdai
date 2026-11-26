"""Read one bounded, sanitized Incident evidence summary from durable audit."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any, Protocol

from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

_PREFIX = re.compile(r"^fdai-[a-z0-9-]{1,120}$")
_DSN_ENV = "FDAI_STATE_STORE_DSN"


class IncidentTransitionReader(Protocol):
    """Read-only Incident transition surface used by the evidence query."""

    async def read_incident_transitions(self) -> tuple[Mapping[str, Any], ...]: ...


def summarize_incident_evidence(
    entries: tuple[Mapping[str, Any], ...],
    *,
    correlation_prefix: str,
) -> dict[str, object]:
    """Return counts only for transitions containing the exact bounded prefix."""

    if _PREFIX.fullmatch(correlation_prefix) is None:
        raise ValueError("incident evidence correlation prefix is invalid")
    matched = tuple(
        entry
        for entry in entries
        if correlation_prefix
        in json.dumps(entry, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    )
    incident_ids = {
        value for entry in matched if isinstance((value := entry.get("incident_id")), str) and value
    }
    member_counts = (
        len(value)
        for entry in matched
        if isinstance((value := entry.get("member_event_ids")), list)
    )
    kinds = sorted(
        {value for entry in matched if isinstance((value := entry.get("kind")), str) and value}
    )
    return {
        "incidents": len(incident_ids),
        "kinds": kinds,
        "max_members": max(member_counts, default=0),
        "transitions": len(matched),
    }


async def query_incident_evidence(
    *,
    correlation_prefix: str,
    reader: IncidentTransitionReader,
) -> dict[str, object]:
    """Read and summarize one correlation prefix without returning identifiers."""

    return summarize_incident_evidence(
        await reader.read_incident_transitions(),
        correlation_prefix=correlation_prefix,
    )


def main() -> None:
    """Run one read-only query from a Container Apps execution."""

    if len(sys.argv) != 2:
        raise ValueError("incident evidence query requires one correlation prefix")
    dsn = os.environ.get(_DSN_ENV, "").strip()
    if not dsn:
        raise ValueError(f"{_DSN_ENV} MUST NOT be empty")
    result = asyncio.run(
        query_incident_evidence(
            correlation_prefix=sys.argv[1],
            reader=PostgresStateStore(
                config=PostgresStateStoreConfig(
                    dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
                )
            ),
        )
    )
    print("incident-evidence:" + json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
