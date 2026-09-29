"""Retain content-free authentication receipts before semantic transport emits references."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import psycopg
from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationProposal,
    ConversationProposalOutbox,
    OutboxReceipt,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.postgres import _psycopg_dsn
from psycopg.rows import dict_row


class AuthenticationReceiptWriter(Protocol):
    """Write one content-free receipt before its reference can be sent to Core."""

    async def retain(
        self,
        *,
        receipt_digest: str,
        request_id: str,
        principal_id: str,
        receipt: Mapping[str, object],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PostgresAuthenticationReceiptWriter:
    """Insert receipts through the Operator role; duplicates are idempotent."""

    dsn: str
    connect_timeout_s: int = 10
    statement_timeout_ms: int = 20_000

    async def retain(
        self,
        *,
        receipt_digest: str,
        request_id: str,
        principal_id: str,
        receipt: Mapping[str, object],
    ) -> None:
        """Create the receipt row once, or fail before semantic publication."""

        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self.dsn),
                row_factory=dict_row,
                connect_timeout=self.connect_timeout_s,
            ) as connection:
                async with connection.transaction():
                    await connection.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (str(self.statement_timeout_ms),),
                    )
                    await connection.execute(
                        """
                        INSERT INTO operator_authentication_receipt (
                            receipt_digest, request_id, principal_id, receipt
                        )
                        VALUES (%s, %s, %s, %s::jsonb)
                        """,
                        (
                            receipt_digest,
                            request_id,
                            principal_id,
                            json.dumps(dict(receipt), separators=(",", ":"), sort_keys=True),
                        ),
                    )
        except psycopg.errors.UniqueViolation:
            return
        except psycopg.Error as exc:
            raise ConversationBoundaryError(
                503,
                "authentication_receipt_unavailable",
                "semantic authentication receipt retention is unavailable",
            ) from exc


@dataclass(frozen=True, slots=True)
class AuthenticationReceiptRetainingOutbox:
    """Wrap the semantic outbox so Core never sees an unresolved receipt reference."""

    delegate: ConversationProposalOutbox
    builder: SemanticTurnEnvelopeBuilder
    writer: AuthenticationReceiptWriter

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        """Retain the referenced receipt before forwarding the semantic proposal."""

        envelope = self.builder.build(proposal)
        semantic = envelope.get("semantic_turn")
        if not isinstance(semantic, Mapping):
            raise ConversationBoundaryError(
                400,
                "semantic_request_invalid",
                "semantic request is invalid",
            )
        receipt_ref = semantic.get("authentication_receipt_ref")
        if isinstance(receipt_ref, str):
            receipt = proposal.authentication_receipt
            if receipt is None or receipt.get("receipt_digest") != receipt_ref:
                raise ConversationBoundaryError(
                    400,
                    "authentication_receipt_invalid",
                    "semantic authentication receipt is invalid",
                )
            request_id = envelope.get("request_id")
            if not isinstance(request_id, str):
                raise ConversationBoundaryError(
                    400,
                    "semantic_request_invalid",
                    "semantic request id is invalid",
                )
            await self.writer.retain(
                receipt_digest=receipt_ref,
                request_id=request_id,
                principal_id=proposal.scope.subject_id,
                receipt=receipt,
            )
        return await self.delegate.append(proposal)


__all__ = [
    "AuthenticationReceiptRetainingOutbox",
    "AuthenticationReceiptWriter",
    "PostgresAuthenticationReceiptWriter",
]
