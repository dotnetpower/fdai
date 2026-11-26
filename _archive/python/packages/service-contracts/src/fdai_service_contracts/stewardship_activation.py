"""Authority-free Owner request to activate one Console stewardship revision candidate."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

STEWARDSHIP_ACTIVATION_OPERATION = "stewardship.candidate_activation"
CANDIDATE_ID_PATTERN = r"^[0-9a-f]{16}$"
CANDIDATE_DIGEST_PATTERN = r"^[0-9a-f]{64}$"


class StewardshipCandidateActivationBody(BaseModel):
    """Owner intent bound to the exact candidate bytes the Owner reviewed.

    The request carries no YAML, role, or approval claim. Core re-reads the stored candidate,
    rechecks the stored Owner role, and refuses the activation when the digest differs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: str = Field(pattern=CANDIDATE_ID_PATTERN)
    candidate_digest: str = Field(pattern=CANDIDATE_DIGEST_PATTERN)


__all__ = [
    "CANDIDATE_DIGEST_PATTERN",
    "CANDIDATE_ID_PATTERN",
    "STEWARDSHIP_ACTIVATION_OPERATION",
    "StewardshipCandidateActivationBody",
]
