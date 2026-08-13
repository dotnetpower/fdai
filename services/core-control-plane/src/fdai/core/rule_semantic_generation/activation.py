"""Exact activation binding for governed Rule semantic generations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationActivationCommandEvent,
    RuleGenerationActivationResultEvent,
    RuleGenerationActivationStatus,
    RuleGenerationIdentity,
    RuleGenerationValidationResultEvent,
)
from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogGenerationMetadata,
    CatalogGenerationStaleError,
    CatalogSemanticIndex,
)
from fdai.shared.providers.event_bus import EventBus

from .ledger import RuleGenerationOutboxLedger
from .publication import RULE_GENERATION_ACTIVATION_COMMAND_TOPIC


class RuleGenerationActivationBinder:
    """Apply one exact activation command and atomically close its durable result.

    Replay checks precede provider access. The semantic index remains the active-pointer
    authority, while the ledger makes the first terminal result and its projection outbox
    durable. Provider failures never grant activation authority.
    """

    def __init__(
        self,
        *,
        index: CatalogSemanticIndex,
        ledger: RuleGenerationOutboxLedger,
        event_bus: EventBus | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._index = index
        self._ledger = ledger
        self._event_bus = event_bus
        self._clock = clock or (lambda: datetime.now(UTC))

    async def active_generation_identity(
        self,
        corpus: CatalogCorpus,
    ) -> RuleGenerationIdentity | None:
        """Read the exact current pointer identity for Mimir command construction."""

        active = await self._index.active_generation(corpus)
        return RuleGenerationIdentity.from_metadata(active) if active is not None else None

    async def bind_validation_result(
        self,
        result: RuleGenerationValidationResultEvent,
    ) -> None:
        """Bind one exact Heimdall receipt to its staged target before publication."""

        validated = RuleGenerationValidationResultEvent.model_validate_json(
            result.model_dump_json()
        )
        receipt_digest = validated.validation_receipt_digest
        if not validated.valid or receipt_digest is None:
            raise ValueError("invalid Rule generation evidence cannot bind validation")
        target = validated.build_result.generation
        bound = await self._index.bind_generation_validation(
            target.generation_id,
            expected_generation_digest=target.generation_digest,
            validation_receipt_digest=receipt_digest,
        )
        if (
            RuleGenerationIdentity.from_metadata(bound) != target
            or bound.validation_receipt_digest != receipt_digest
        ):
            raise ValueError("Rule generation validation binding identity mismatch")

    async def publish_command(
        self,
        command: RuleGenerationActivationCommandEvent,
    ) -> None:
        """Publish one Mimir-owned command through the bound typed transport."""

        validated = RuleGenerationActivationCommandEvent.model_validate_json(
            command.model_dump_json()
        )
        if self._event_bus is None:
            raise RuntimeError("Rule generation activation command transport is unavailable")
        request_id = validated.validation_result.build_result.request.generation_request_id
        receipt = await self._event_bus.publish(
            RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
            request_id,
            validated.model_dump(mode="json"),
        )
        if receipt.topic != RULE_GENERATION_ACTIVATION_COMMAND_TOPIC:
            raise RuntimeError("Rule generation activation command broker receipt mismatch")

    async def handle(
        self,
        command: RuleGenerationActivationCommandEvent,
    ) -> RuleGenerationActivationResultEvent:
        """Validate and close one command without replaying a completed provider effect."""

        validated = RuleGenerationActivationCommandEvent.model_validate_json(
            command.model_dump_json()
        )
        existing = await self._ledger.result_for(validated)
        if existing is not None:
            return existing

        status, failure_reason = await self._activate(validated)
        result = RuleGenerationActivationResultEvent.create(
            command=validated,
            status=status,
            completed_at=self._completed_at(validated.commanded_at),
            failure_reason=failure_reason,
        )
        return await self._ledger.commit_result(result)

    async def _activate(
        self,
        command: RuleGenerationActivationCommandEvent,
    ) -> tuple[RuleGenerationActivationStatus, str | None]:
        target = command.validation_result.build_result.generation
        receipt_digest = command.validation_result.validation_receipt_digest
        if receipt_digest is None:
            return RuleGenerationActivationStatus.FAILED, "validation_receipt_unavailable"

        active = await self._index.active_generation(target.corpus.value)
        observed = _target_status(
            active,
            target=target,
            receipt_digest=receipt_digest,
            commanded_at=command.commanded_at,
        )
        if observed is not None:
            return observed, None
        if active is not None and _metadata_identity(active) == target:
            return RuleGenerationActivationStatus.FAILED, "target_validation_receipt_mismatch"
        if not _matches_expected(active, command.expected_active_generation):
            return RuleGenerationActivationStatus.FAILED, "active_generation_identity_mismatch"

        expected = command.expected_active_generation
        try:
            activated = await self._index.activate_generation(
                target.generation_id,
                expected_generation_digest=target.generation_digest,
                expected_active_generation_id=(
                    expected.generation_id if expected is not None else None
                ),
                expected_active_generation_digest=(
                    expected.generation_digest if expected is not None else None
                ),
                activated_at=command.commanded_at,
                expected_validation_receipt_digest=receipt_digest,
            )
        except CatalogGenerationStaleError:
            failure_reason = "active_generation_identity_mismatch"
        except ValueError:
            failure_reason = "target_activation_precondition_failed"
        except Exception:
            failure_reason = "activation_provider_error"
        else:
            status = _target_status(
                activated,
                target=target,
                receipt_digest=receipt_digest,
                commanded_at=command.commanded_at,
            )
            if status is None:
                return (
                    RuleGenerationActivationStatus.FAILED,
                    "activated_generation_identity_mismatch",
                )
            return status, None

        try:
            active_after_error = await self._index.active_generation(target.corpus.value)
        except Exception:
            return RuleGenerationActivationStatus.FAILED, failure_reason
        recovered = _target_status(
            active_after_error,
            target=target,
            receipt_digest=receipt_digest,
            commanded_at=command.commanded_at,
        )
        if recovered is not None:
            return recovered, None
        return RuleGenerationActivationStatus.FAILED, failure_reason

    def _completed_at(self, commanded_at: datetime) -> datetime:
        completed_at = self._clock()
        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("Rule generation activation clock MUST be timezone-aware")
        return max(completed_at, commanded_at)


def _matches_expected(
    active: CatalogGenerationMetadata | None,
    expected: RuleGenerationIdentity | None,
) -> bool:
    if active is None or expected is None:
        return active is None and expected is None
    return _metadata_identity(active) == expected


def _target_status(
    active: CatalogGenerationMetadata | None,
    *,
    target: RuleGenerationIdentity,
    receipt_digest: str,
    commanded_at: datetime,
) -> RuleGenerationActivationStatus | None:
    if (
        active is None
        or _metadata_identity(active) != target
        or active.validation_receipt_digest != receipt_digest
    ):
        return None
    if active.activated_at == commanded_at:
        return RuleGenerationActivationStatus.ACTIVATED
    return RuleGenerationActivationStatus.ALREADY_ACTIVE


def _metadata_identity(metadata: CatalogGenerationMetadata) -> RuleGenerationIdentity:
    return RuleGenerationIdentity.from_metadata(metadata)


__all__ = ["RuleGenerationActivationBinder"]
