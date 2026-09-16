"""Authority-free requester consent to contact one report-line approval route."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReportLineContactCommand(BaseModel):
    """One authenticated requester choice that is not an action approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    message_kind: Literal["report_line_contact"] = "report_line_contact"
    approval_id: Annotated[str, Field(min_length=1, max_length=200)]
    requester_ref: Annotated[str, Field(min_length=1, max_length=256)]
    consent: bool
    expected_consent_revision: Annotated[int, Field(strict=True, ge=0)]
    requested_at: datetime
    idempotency_key: Annotated[str, Field(min_length=1, max_length=256)]
    command_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    approval_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _exact_command(self) -> ReportLineContactCommand:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("report-line contact requested_at MUST be timezone-aware")
        if self.requester_ref != self.requester_ref.strip().casefold():
            raise ValueError("report-line contact requester MUST be normalized")
        if self.command_digest != report_line_contact_digest(self):
            raise ValueError("report-line contact command digest does not match its content")
        return self


def report_line_contact_digest(command: ReportLineContactCommand) -> str:
    """Return the canonical digest excluding the digest field itself."""

    value = command.model_dump(mode="json", exclude={"command_digest"})
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_report_line_contact_command(
    *,
    approval_id: str,
    requester_ref: str,
    consent: bool,
    expected_consent_revision: int,
    requested_at: datetime,
    idempotency_key: str,
) -> ReportLineContactCommand:
    """Build one self-digesting contact command from server-authenticated values."""

    normalized_requester = requester_ref.strip().casefold()
    provisional = ReportLineContactCommand.model_construct(
        approval_id=approval_id,
        requester_ref=normalized_requester,
        consent=consent,
        expected_consent_revision=expected_consent_revision,
        requested_at=requested_at,
        idempotency_key=idempotency_key,
        command_digest="0" * 64,
        approval_authority=False,
        execution_authority=False,
    )
    return ReportLineContactCommand(
        approval_id=approval_id,
        requester_ref=normalized_requester,
        consent=consent,
        expected_consent_revision=expected_consent_revision,
        requested_at=requested_at,
        idempotency_key=idempotency_key,
        command_digest=report_line_contact_digest(provisional),
    )


__all__ = [
    "ReportLineContactCommand",
    "build_report_line_contact_command",
    "report_line_contact_digest",
]
