from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fdai_operator_service.families.iam.report_line_contact_outbox import (
    DurableReportLineContactPublisher,
    ReportLineContactOutboxDrainer,
)
from fdai_service_contracts import (
    ReportLineContactCommand,
    build_report_line_contact_command,
)

NOW = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)


class Durable:
    def __init__(self) -> None:
        self.persisted: list[ReportLineContactCommand] = []

    async def enqueue_report_line_contact(
        self,
        command: ReportLineContactCommand,
    ) -> None:
        self.persisted.append(command)


class Publisher:
    def __init__(self, durable: Durable | None = None) -> None:
        self.durable = durable
        self.published: list[tuple[str, str, object]] = []

    async def publish(self, topic: str, key: str, payload):
        if self.durable is not None:
            assert self.durable.persisted
        self.published.append((topic, key, payload))
        return object()


class Ledger:
    def __init__(self) -> None:
        self.closed: list[str] = []

    async def mark_report_line_contact_published(self, idempotency_key: str) -> bool:
        self.closed.append(idempotency_key)
        return True


@dataclass(frozen=True)
class Claim:
    key: str
    claim_id: str
    payload: dict[str, object]


class ClaimStore:
    def __init__(self, command: ReportLineContactCommand) -> None:
        self.claim: Claim | None = Claim(
            "proposal-key",
            "claim-id",
            command.model_dump(mode="json"),
        )
        self.published = False

    async def claim_report_line_contact_proposal(self, *, worker_id, lease_seconds):
        del worker_id, lease_seconds
        claim, self.claim = self.claim, None
        return claim

    async def mark_proposal_published(self, *, key, claim_id):
        assert key == "proposal-key" and claim_id == "claim-id"
        self.published = True
        return True

    async def mark_proposal_rejected(self, *, key, claim_id, reason_code):
        raise AssertionError((key, claim_id, reason_code))

    async def release_proposal_claim(self, *, key, claim_id):
        raise AssertionError((key, claim_id))


def _command() -> ReportLineContactCommand:
    return build_report_line_contact_command(
        approval_id="approval-1",
        requester_ref="person-a",
        consent=True,
        expected_consent_revision=0,
        requested_at=NOW,
        idempotency_key="contact-1",
    )


async def test_immediate_contact_delivery_persists_before_publish() -> None:
    durable = Durable()
    publisher = Publisher(durable)
    ledger = Ledger()
    outbox = DurableReportLineContactPublisher(
        durable=durable,  # type: ignore[arg-type]
        publisher=publisher,
        topic="hil-decisions",
        ledger=ledger,
    )

    await outbox.enqueue_report_line_contact(_command())

    assert len(durable.persisted) == 1
    assert publisher.published[0][1] == "approval-1"
    assert ledger.closed == ["contact-1"]


async def test_contact_drainer_replays_the_exact_typed_command() -> None:
    command = _command()
    store = ClaimStore(command)
    publisher = Publisher()
    drainer = ReportLineContactOutboxDrainer(
        store=store,
        publisher=publisher,
        topic="hil-decisions",
    )

    assert await drainer.run_once() is True
    assert store.published is True
    assert publisher.published[0][2] == command.model_dump(mode="json")


async def test_postgres_store_claims_only_contact_consent_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai_operator_service.postgres_family_store import (
        PostgresFamilyStore,
        PostgresFamilyStoreConfig,
    )

    statements: list[str] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, parameters
        statements.append(statement)
        return [
            {
                "key": "operator-proposal:iam:contact",
                "value": {"payload": _command().model_dump(mode="json"), "attempt": 1},
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    claim = await store.claim_report_line_contact_proposal(
        worker_id="contact-worker",
        lease_seconds=30,
    )

    assert claim is not None
    assert ReportLineContactCommand.model_validate(claim.payload) == _command()
    assert "value ->> 'operation' = 'hil.report-line-contact.enqueue'" in statements[0]
    assert "FOR UPDATE SKIP LOCKED" in statements[0]


async def test_postgres_store_closes_only_pending_contact_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai_operator_service.postgres_family_store import (
        PostgresFamilyStore,
        PostgresFamilyStoreConfig,
    )

    statements: list[str] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, parameters
        statements.append(statement)
        return []

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    assert await store.mark_report_line_contact_published("contact-1") is False
    assert "value ->> 'dispatch_status' = 'pending'" in statements[0]
    with pytest.raises(ValueError, match="idempotency_key MUST be"):
        await store.mark_report_line_contact_published(" ")
