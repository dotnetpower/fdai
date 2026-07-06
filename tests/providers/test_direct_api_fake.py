"""RecordingDirectApiExecutor - invariant tests for the in-memory fake.

Mirrors the shape of ``test_remediation_pr_fake.py``: the fake is the
source of truth for what a real substrate adapter would have been asked
to do, and it MUST honour idempotency, the enforce-mode promotion
contract, and the STOPPED / FAILED / PRECONDITION_FAILED outcome paths.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from aiopspilot.shared.contracts.models import Mode
from aiopspilot.shared.providers.direct_api import (
    DirectApiError,
    DirectApiExecutor,
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)
from aiopspilot.shared.providers.testing import RecordingDirectApiExecutor
from aiopspilot.shared.providers.testing.direct_api import (
    RecordingDirectApiExecutor as _AlsoImportable,
)


def _req(
    *,
    idempotency_key: str = "k1",
    mode: Mode = Mode.SHADOW,
    labels: tuple[str, ...] = ("shadow",),
    action_type_name: str = "ops.restart-service",
    resource_ref: str = "res-1",
    arguments: dict[str, Any] | None = None,
) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key=idempotency_key,
        action_type_name=action_type_name,
        rule_ids=("r1",),
        resource_ref=resource_ref,
        arguments=arguments or {},
        labels=labels,
        mode=mode,
    )


class TestProtocolConformance:
    def test_recording_fake_satisfies_protocol(self) -> None:
        pub: DirectApiExecutor = RecordingDirectApiExecutor()
        assert isinstance(pub, DirectApiExecutor)

    def test_top_level_re_export_is_the_same_class(self) -> None:
        assert RecordingDirectApiExecutor is _AlsoImportable


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_first_call_produces_succeeded_receipt(self) -> None:
        pub = RecordingDirectApiExecutor()
        receipt = await pub.execute(_req())
        assert receipt.outcome is DirectApiOutcome.SUCCEEDED
        assert receipt.receipt_ref.startswith("call-")
        assert receipt.already_existed is False
        assert receipt.rollback_succeeded is None

    @pytest.mark.asyncio
    async def test_receipt_ref_increments(self) -> None:
        pub = RecordingDirectApiExecutor()
        r1 = await pub.execute(_req(idempotency_key="k1"))
        r2 = await pub.execute(_req(idempotency_key="k2"))
        assert r1.receipt_ref != r2.receipt_ref

    @pytest.mark.asyncio
    async def test_records_captured_in_order(self) -> None:
        pub = RecordingDirectApiExecutor()
        await pub.execute(_req(idempotency_key="k1"))
        await pub.execute(_req(idempotency_key="k2"))
        assert len(pub.records) == 2
        assert pub.records[0].idempotency_key == "k1"
        assert pub.records[1].idempotency_key == "k2"

    @pytest.mark.asyncio
    async def test_records_is_a_tuple_snapshot(self) -> None:
        pub = RecordingDirectApiExecutor()
        await pub.execute(_req())
        first_snapshot = pub.records
        await pub.execute(_req(idempotency_key="k2"))
        # First snapshot MUST NOT reflect the later addition.
        assert len(first_snapshot) == 1

    @pytest.mark.asyncio
    async def test_find_by_idempotency_key(self) -> None:
        pub = RecordingDirectApiExecutor()
        await pub.execute(_req(idempotency_key="target"))
        record = pub.find("target")
        assert record is not None
        assert record.idempotency_key == "target"
        assert pub.find("nope") is None


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_key_returns_already_applied(self) -> None:
        pub = RecordingDirectApiExecutor()
        first = await pub.execute(_req(idempotency_key="dup"))
        second = await pub.execute(_req(idempotency_key="dup"))
        assert first.outcome is DirectApiOutcome.SUCCEEDED
        assert second.outcome is DirectApiOutcome.ALREADY_APPLIED
        assert second.already_existed is True
        assert second.receipt_ref == first.receipt_ref

    @pytest.mark.asyncio
    async def test_duplicate_key_does_not_double_record(self) -> None:
        pub = RecordingDirectApiExecutor()
        await pub.execute(_req(idempotency_key="dup"))
        await pub.execute(_req(idempotency_key="dup"))
        assert len(pub.records) == 1

    @pytest.mark.asyncio
    async def test_seed_outcome_short_circuits_first_call(self) -> None:
        pub = RecordingDirectApiExecutor()
        pub.seed_outcome(
            "pre",
            DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref="seed-1",
                detail="pre-seeded",
            ),
        )
        receipt = await pub.execute(_req(idempotency_key="pre"))
        assert receipt.outcome is DirectApiOutcome.ALREADY_APPLIED
        assert receipt.receipt_ref == "seed-1"
        # No record produced because ledger short-circuited.
        assert len(pub.records) == 0


class TestPromotionContract:
    @pytest.mark.asyncio
    async def test_enforce_without_label_is_rejected(self) -> None:
        pub = RecordingDirectApiExecutor()
        with pytest.raises(DirectApiPromotionError):
            await pub.execute(_req(mode=Mode.ENFORCE, labels=("shadow",)))

    @pytest.mark.asyncio
    async def test_enforce_with_enforce_label_succeeds(self) -> None:
        pub = RecordingDirectApiExecutor()
        receipt = await pub.execute(_req(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
        assert receipt.outcome is DirectApiOutcome.SUCCEEDED

    def test_promotion_error_is_a_direct_api_error(self) -> None:
        exc = DirectApiPromotionError("nope")
        assert isinstance(exc, DirectApiError)
        assert exc.kind == "promotion"

    def test_precondition_error_kind(self) -> None:
        exc = DirectApiPreconditionError("cannot run")
        assert isinstance(exc, DirectApiError)
        assert exc.kind == "precondition"


class TestForcedOutcomes:
    @pytest.mark.asyncio
    async def test_force_stopped_does_not_cache_success(self) -> None:
        pub = RecordingDirectApiExecutor()
        pub.force_outcome(DirectApiOutcome.STOPPED, rollback_succeeded=True)
        receipt = await pub.execute(_req(idempotency_key="k"))
        assert receipt.outcome is DirectApiOutcome.STOPPED
        assert receipt.rollback_succeeded is True
        # A retry MUST get a fresh happy-path call, not ALREADY_APPLIED.
        retry = await pub.execute(_req(idempotency_key="k"))
        assert retry.outcome is DirectApiOutcome.SUCCEEDED

    @pytest.mark.asyncio
    async def test_force_failed_with_manual_rollback_flag(self) -> None:
        pub = RecordingDirectApiExecutor()
        pub.force_outcome(
            DirectApiOutcome.FAILED,
            rollback_succeeded=False,
            detail="upstream 500",
        )
        receipt = await pub.execute(_req())
        assert receipt.outcome is DirectApiOutcome.FAILED
        assert receipt.rollback_succeeded is False
        assert receipt.detail == "upstream 500"

    @pytest.mark.asyncio
    async def test_force_precondition_failed(self) -> None:
        pub = RecordingDirectApiExecutor()
        pub.force_outcome(DirectApiOutcome.PRECONDITION_FAILED)
        receipt = await pub.execute(_req())
        assert receipt.outcome is DirectApiOutcome.PRECONDITION_FAILED
        assert receipt.rollback_succeeded is None

    @pytest.mark.asyncio
    async def test_force_outcome_is_one_shot(self) -> None:
        pub = RecordingDirectApiExecutor()
        pub.force_outcome(DirectApiOutcome.STOPPED)
        first = await pub.execute(_req(idempotency_key="a"))
        second = await pub.execute(_req(idempotency_key="b"))
        assert first.outcome is DirectApiOutcome.STOPPED
        assert second.outcome is DirectApiOutcome.SUCCEEDED


class TestErrorInjection:
    @pytest.mark.asyncio
    async def test_next_error_raises_once(self) -> None:
        pub = RecordingDirectApiExecutor()
        pub.next_error(RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await pub.execute(_req(idempotency_key="a"))
        # Next call is clean again.
        receipt = await pub.execute(_req(idempotency_key="b"))
        assert receipt.outcome is DirectApiOutcome.SUCCEEDED

    @pytest.mark.asyncio
    async def test_error_does_not_cache_a_receipt(self) -> None:
        pub = RecordingDirectApiExecutor()
        pub.next_error(RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            await pub.execute(_req(idempotency_key="k"))
        # A retry after the error MUST get a fresh happy-path call, not
        # ALREADY_APPLIED - the ledger stayed clean.
        retry = await pub.execute(_req(idempotency_key="k"))
        assert retry.outcome is DirectApiOutcome.SUCCEEDED


class TestRequestValidation:
    def test_request_is_frozen(self) -> None:
        req = _req()
        with pytest.raises((AttributeError, TypeError)):
            req.action_id = UUID(int=42)  # type: ignore[misc]

    def test_default_mode_is_shadow(self) -> None:
        req = _req()
        assert req.mode is Mode.SHADOW
        assert req.labels == ("shadow",)
