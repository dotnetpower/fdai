"""Atomic embedded outbox and Saga audit lineage for retained Twin records."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts import AgentOperationalActivity

from fdai.core.assurance_twin.posture_activity import AssuranceTwinReviewActivity
from fdai.shared.providers.state_store import StateStore

POSTURE_REPORT_STATE_PREFIX = "runtime:assurance-twin-posture:"
CHANGE_REVIEW_STATE_PREFIX = "runtime:assurance-twin-review:"
_PUBLICATION_FIELD = "publication_outbox"
_REVISION_FIELD = "revision"


def _owner_prefix(owner: str) -> str:
    if owner == "Heimdall":
        return POSTURE_REPORT_STATE_PREFIX
    if owner == "Forseti":
        return CHANGE_REVIEW_STATE_PREFIX
    raise ValueError("assurance twin outbox owner MUST be Heimdall or Forseti")


def _pending_publication(
    activity: AgentOperationalActivity | AssuranceTwinReviewActivity | None,
    *,
    owner: str,
    digest: str,
    revision: int,
) -> dict[str, Any]:
    if activity is None:
        return {}
    if activity.owner_agent != owner or activity.execution_authority is not False:
        raise ValueError("assurance twin publication owner or authority is invalid")
    return {
        _PUBLICATION_FIELD: {
            "record_revision": revision,
            "evidence_digest": digest,
            "owner_agent": owner,
            "activity": activity.model_dump(mode="json"),
            "published": False,
        }
    }


def _advance_publication(value: Mapping[str, Any], *, revision: int) -> dict[str, Any]:
    raw = value.get(_PUBLICATION_FIELD)
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise RuntimeError("assurance twin publication outbox is malformed")
    return {_PUBLICATION_FIELD: {**raw, "record_revision": revision}}


def _audit_lineage(
    *,
    kind: str,
    correlation_id: str,
    digest: str,
    revision: int,
    owner: str,
    key: str,
) -> dict[str, object]:
    """Saga-owned append-only lineage, committed with the owned record."""

    if not key.strip() or len(key) > 512:
        raise ValueError("assurance twin audit key MUST be non-blank and bounded")
    identity = f"sha256:{hashlib.sha256(key.encode('utf-8')).hexdigest()}"
    return {
        "action_kind": f"assurance_twin.{kind}",
        "actor": "fdai.system",
        "owner_agent": "Saga",
        "subject_owner_agent": owner,
        "mode": "shadow",
        "correlation_id": correlation_id,
        "evidence_digest": digest,
        "record_revision": revision,
        "idempotency_key": f"assurance-twin:{kind}:{identity}:{revision}:{digest}",
    }


class AssuranceTwinOutboxMixin:
    """Store-backed relay operations kept separate from evidence serialization."""

    _store: StateStore

    async def pending_publications(
        self, *, owner: str, limit: int = 100
    ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        """Read bounded durable candidates; the relay rechecks each before sending."""

        prefix = _owner_prefix(owner)
        if not 1 <= limit <= 100:
            raise ValueError("assurance twin outbox limit MUST be in [1, 100]")
        candidates: list[tuple[str, Mapping[str, Any]]] = []
        for offset in range(0, 1000, 100):
            rows, total = await self._store.read_state_page(prefix, limit=100, offset=offset)
            if total > 1000:
                raise RuntimeError("assurance twin outbox scan exceeds bounded capacity")
            for row in rows:
                outbox = row.get(_PUBLICATION_FIELD)
                if isinstance(outbox, Mapping) and outbox.get("published") is False:
                    identity = row.get("scope" if owner == "Heimdall" else "review_key")
                    if not isinstance(identity, str):
                        raise RuntimeError("assurance twin outbox record identity is malformed")
                    candidates.append((f"{prefix}{identity}", row))
                    if len(candidates) >= limit:
                        return tuple(candidates)
            if offset + 100 >= total:
                break
        return tuple(candidates)

    async def read_publication(self, key: str, *, owner: str) -> Mapping[str, Any] | None:
        if not key.startswith(_owner_prefix(owner)):
            raise ValueError("assurance twin outbox owner does not own the record")
        return await self._store.read_state(key)

    async def mark_published(self, key: str, *, owner: str, revision: int, digest: str) -> bool:
        """Acknowledge only the same durable evidence revision, with Saga lineage."""

        row = await self.read_publication(key, owner=owner)
        if row is None or row.get(_REVISION_FIELD) != revision:
            return False
        outbox = row.get(_PUBLICATION_FIELD)
        if (
            not isinstance(outbox, Mapping)
            or outbox.get("record_revision") != revision
            or outbox.get("evidence_digest") != digest
            or outbox.get("published") is not False
        ):
            return False
        return await self._store.compare_and_set_state_with_audit(
            key,
            {
                **row,
                _REVISION_FIELD: revision + 1,
                _PUBLICATION_FIELD: {**outbox, "published": True},
            },
            expected_revision=revision,
            audit_entry=_audit_lineage(
                kind="publication_acknowledged",
                correlation_id=str(row["correlation_id"]),
                digest=digest,
                revision=revision,
                owner=owner,
                key=key,
            ),
        )


__all__ = [
    "CHANGE_REVIEW_STATE_PREFIX",
    "POSTURE_REPORT_STATE_PREFIX",
    "AssuranceTwinOutboxMixin",
]
