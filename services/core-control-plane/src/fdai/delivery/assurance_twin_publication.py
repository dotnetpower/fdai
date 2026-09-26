"""Independent Heimdall/Forseti outbox relays for advisory Twin activities."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, Literal

from fdai_service_contracts import AgentOperationalActivity
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.core.assurance_twin.posture_activity import (
    AssuranceTwinReviewActivity,
)
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    StateStoreAssuranceTwinPostureLedger,
    evidence_body_digest,
)
from fdai.shared.providers.event_bus import EventBus

_LOG = logging.getLogger(__name__)
PUBLICATION_TOPIC = "fdai.assurance-twin.publications"
_PROVENANCE = frozenset(
    {
        "activity_id",
        "correlation_id",
        "evidence_digest",
        "evidence_source_revision",
        "revision",
        "conflict",
        "publication_outbox",
    }
)


class AssuranceTwinPublicationEvent(BaseModel):
    """Local schema binding an advisory tip to its exact durable revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: Literal["posture", "review"]
    owner_agent: Literal["Heimdall", "Forseti"]
    record_revision: int = Field(ge=1)
    evidence_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_source_revision: str = Field(min_length=1, max_length=512)
    idempotency_key: str = Field(min_length=1, max_length=512)
    activity: AgentOperationalActivity | AssuranceTwinReviewActivity
    current: Literal[False] = False
    publication_complete: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def check_ownership(self) -> AssuranceTwinPublicationEvent:
        if (
            (self.kind == "posture") != (self.owner_agent == "Heimdall")
            or self.activity.owner_agent != self.owner_agent
            or self.idempotency_key != self.activity.idempotency_key
            or self.activity.execution_authority is not False
        ):
            raise ValueError("assurance twin publication owner or activity identity diverges")
        return self


class AssuranceTwinOutboxPublisher:
    """Relay one owner's exact retained revision, never an ingress payload.

    Broker acknowledgement is not an operational outcome. A crash after send
    may replay the same stable idempotency key; consumers must deduplicate and
    consult the retained revision before treating a tip as current.
    """

    def __init__(
        self,
        *,
        owner: str,
        ledger: StateStoreAssuranceTwinPostureLedger,
        bus: EventBus,
    ) -> None:
        if owner not in {"Heimdall", "Forseti"}:
            raise ValueError("assurance twin publisher owner is not a writer")
        self._owner = owner
        self._ledger = ledger
        self._bus = bus

    async def publish_pending(self) -> int:
        """Send a bounded batch and retain failures for restart recovery."""

        published = 0
        for key, _ in await self._ledger.pending_publications(owner=self._owner):
            row = await self._ledger.read_publication(key, owner=self._owner)
            if row is None:
                continue
            checked = _validated_publication(row, owner=self._owner, key=key)
            if checked is None:
                continue
            activity, revision, digest = checked
            event = AssuranceTwinPublicationEvent(
                kind="posture" if self._owner == "Heimdall" else "review",
                owner_agent=self._owner,  # type: ignore[arg-type]
                record_revision=revision,
                evidence_digest=digest,
                evidence_source_revision=str(row["evidence_source_revision"]),
                idempotency_key=activity.idempotency_key,
                activity=activity,
            )
            try:
                await self._bus.publish(
                    PUBLICATION_TOPIC, event.idempotency_key, event.model_dump(mode="json")
                )
            except Exception:  # noqa: BLE001 - preserve pending outbox on unknown transport result
                _LOG.warning(
                    "assurance_twin_publication_unacknowledged", extra={"owner": self._owner}
                )
                continue
            if await self._ledger.mark_published(
                key, owner=self._owner, revision=revision, digest=digest
            ):
                published += 1
        return published

    @property
    def owner(self) -> str:
        return self._owner

    async def run(self, stop: asyncio.Event, *, interval_seconds: float = 5.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("assurance twin outbox interval MUST be positive")
        while not stop.is_set():
            await self.publish_pending()
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass


def _validated_publication(
    row: Mapping[str, Any], *, owner: str, key: str
) -> tuple[AgentOperationalActivity | AssuranceTwinReviewActivity, int, str] | None:
    """Reject incomplete, conflicted, or substituted durable evidence."""

    if row.get("conflict") is not None:
        return None
    outbox = row.get("publication_outbox")
    if not isinstance(outbox, Mapping) or outbox.get("published") is not False:
        return None
    revision = row.get("revision")
    digest = row.get("evidence_digest")
    identity = row.get("scope" if owner == "Heimdall" else "review_key")
    retained_body = {field: value for field, value in row.items() if field not in _PROVENANCE}
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or not isinstance(digest, str)
        or key
        != (
            f"runtime:assurance-twin-posture:{identity}"
            if owner == "Heimdall"
            else f"runtime:assurance-twin-review:{identity}"
        )
        or outbox.get("record_revision") != revision
        or outbox.get("evidence_digest") != digest
        or outbox.get("owner_agent") != owner
        or evidence_body_digest(retained_body) != digest
    ):
        raise RuntimeError("assurance twin outbox is not bound to the exact retained revision")
    activity = (
        AgentOperationalActivity.model_validate(outbox.get("activity"))
        if owner == "Heimdall"
        else AssuranceTwinReviewActivity.model_validate(outbox.get("activity"))
    )
    if (
        activity.owner_agent != owner
        or activity.activity_id != row.get("activity_id")
        or activity.freshness.value != row.get("freshness")
        or activity.execution_authority is not False
        or activity.evidence_count != len(row.get("findings", ()))
        or activity.reason_codes != tuple(row.get("reason_codes", ()))
        or not isinstance(row.get("evidence_source_revision"), str)
    ):
        raise RuntimeError("assurance twin activity diverges from retained evidence")
    return activity, revision, digest


__all__ = ["PUBLICATION_TOPIC", "AssuranceTwinOutboxPublisher", "AssuranceTwinPublicationEvent"]
