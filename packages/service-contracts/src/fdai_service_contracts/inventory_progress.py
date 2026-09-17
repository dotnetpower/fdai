"""Versioned, identifier-free progress records for authoritative inventory collection."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, cast

from pydantic import Field, model_validator

from fdai_service_contracts.ontology_query import QueryContract, content_digest

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_OPAQUE_ID_PATTERN = r"^[a-z][a-z0-9.-]{0,127}$"
_REASON_PATTERN = r"^[a-z][a-z0-9_]{0,127}$"
_MAX_COUNTER = 10_000_000_000


class InventoryProgressStage(StrEnum):
    """Ordered stages of one complete inventory reconciliation."""

    COUNT = "count"
    COLLECT = "collect"
    STAGE = "stage"
    ENRICH = "enrich"
    VALIDATE = "validate"
    PROMOTE = "promote"
    VERIFY = "verify"
    COMPLETE = "complete"
    FAILED = "failed"


class InventoryProgressState(StrEnum):
    """Current disposition of an inventory collection attempt."""

    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class InventoryProgressFractionBasis(StrEnum):
    """Evidence used to calculate the displayed completion fraction."""

    COUNT = "count"
    PROVIDER_TYPES = "provider_types"
    PAGES = "pages"
    VERIFIED_CLOSURE = "verified_closure"


class InventoryProgressRecord(QueryContract):
    """One hash-chained, count-only progress observation with no provider identifiers."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: Annotated[str, Field(pattern=_OPAQUE_ID_PATTERN)]
    attempt_id: Annotated[str, Field(pattern=_OPAQUE_ID_PATTERN)]
    sequence: Annotated[int, Field(strict=True, ge=1, le=_MAX_COUNTER)]
    previous_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    stage: InventoryProgressStage
    state: InventoryProgressState
    reason_code: Annotated[str, Field(pattern=_REASON_PATTERN)] | None = None
    generation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)] | None = None
    scopes_completed: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    scopes_total: Annotated[int, Field(strict=True, ge=1, le=_MAX_COUNTER)]
    provider_types_completed: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    provider_types_total: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    resources_observed: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    resources_expected: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)] | None = None
    pages_completed: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    pages_expected: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    links_observed: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    unmapped_objects: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    coverage_gaps: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    started_at: datetime
    last_progress_at: datetime
    deadline_at: datetime
    fraction: Annotated[float, Field(strict=True, ge=0.0, le=1.0)]
    fraction_basis: InventoryProgressFractionBasis
    execution_authority: Literal[False] = False
    record_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _record_is_canonical(self) -> InventoryProgressRecord:
        for field_name, value in (
            ("started_at", self.started_at),
            ("last_progress_at", self.last_progress_at),
            ("deadline_at", self.deadline_at),
        ):
            if value.tzinfo is None:
                raise ValueError(f"inventory progress {field_name} MUST include a timezone")
        if not self.started_at <= self.last_progress_at <= self.deadline_at:
            raise ValueError("inventory progress timestamps MUST be ordered")
        if self.scopes_completed > self.scopes_total:
            raise ValueError("inventory progress completed scopes MUST NOT exceed total scopes")
        if self.provider_types_completed > self.provider_types_total:
            raise ValueError(
                "inventory progress completed provider types MUST NOT exceed total provider types"
            )
        if self.pages_completed > self.pages_expected:
            raise ValueError("inventory progress completed pages MUST NOT exceed expected pages")
        if self.state is InventoryProgressState.FAILED:
            if self.stage is not InventoryProgressStage.FAILED or self.reason_code is None:
                raise ValueError(
                    "failed inventory progress MUST include the failed stage and reason"
                )
        elif self.reason_code is not None or self.stage is InventoryProgressStage.FAILED:
            raise ValueError("non-failed inventory progress MUST NOT include a failure reason")
        if self.state is InventoryProgressState.COMPLETE:
            if (
                self.stage is not InventoryProgressStage.COMPLETE
                or self.fraction != 1.0
                or self.fraction_basis is not InventoryProgressFractionBasis.VERIFIED_CLOSURE
            ):
                raise ValueError("complete inventory progress MUST be verified closure at 1.0")
            if self.generation_digest is None:
                raise ValueError("complete inventory progress MUST bind an active generation")
        elif self.fraction >= 1.0:
            raise ValueError("non-terminal inventory progress MUST remain below 1.0")
        if self.stage is InventoryProgressStage.VERIFY and self.generation_digest is None:
            raise ValueError("verify inventory progress MUST bind a generation")
        expected = content_digest(self.model_dump(mode="json", exclude={"record_digest"}))
        if self.record_digest != expected:
            raise ValueError("inventory progress digest does not match its content")
        return self


class InventoryClosureReceipt(QueryContract):
    """Independent readback that can close one full-subscription inventory attempt."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: Annotated[str, Field(pattern=_OPAQUE_ID_PATTERN)]
    attempt_id: Annotated[str, Field(pattern=_OPAQUE_ID_PATTERN)]
    generation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    subscription_root: Literal[True]
    resource_type_filter: Literal[False]
    final_fence: Literal[True]
    provider_coverage_complete: Literal[True]
    truncated: Literal[False]
    active_generation_matches: Literal[True]
    overlay_open: Literal[False]
    child_sources_complete: Literal[True]
    observer_distinct: Literal[True]
    resource_count: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    link_count: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    unmapped_object_count: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    coverage_gap_count: Annotated[int, Field(strict=True, ge=0, le=_MAX_COUNTER)]
    observed_at: datetime
    execution_authority: Literal[False] = False
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _receipt_is_canonical(self) -> InventoryClosureReceipt:
        if self.observed_at.tzinfo is None:
            raise ValueError("inventory closure observed_at MUST include a timezone")
        expected = content_digest(self.model_dump(mode="json", exclude={"receipt_digest"}))
        if self.receipt_digest != expected:
            raise ValueError("inventory closure digest does not match its content")
        return self


def inventory_progress_record_digest(**values: object) -> str:
    """Return the canonical digest for fields accepted by an inventory progress record."""

    candidate = InventoryProgressRecord.model_construct(
        record_digest="",
        **cast(dict[str, Any], values),
    )
    return content_digest(candidate.model_dump(mode="json", exclude={"record_digest"}))


def inventory_closure_receipt_digest(**values: object) -> str:
    """Return the canonical digest for fields accepted by an inventory closure receipt."""

    candidate = InventoryClosureReceipt.model_construct(
        receipt_digest="",
        **cast(dict[str, Any], values),
    )
    return content_digest(candidate.model_dump(mode="json", exclude={"receipt_digest"}))


__all__ = [
    "InventoryClosureReceipt",
    "InventoryProgressFractionBasis",
    "InventoryProgressRecord",
    "InventoryProgressStage",
    "InventoryProgressState",
    "inventory_closure_receipt_digest",
    "inventory_progress_record_digest",
]
