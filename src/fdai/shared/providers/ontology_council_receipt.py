"""Content-free outcome receipts for ontology model council decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_PROPERTY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class CouncilOutcome(StrEnum):
    CONSENSUS = "consensus"
    CONTESTED = "contested"
    UNSUPPORTED = "unsupported"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class OntologyCouncilReceipt:
    """Replay evidence that excludes source text and model reasoning."""

    claim_digest: str
    packet_digest: str
    policy_digest: str
    model_digests: tuple[str, str, str]
    initial_vote_digests: tuple[str, str, str]
    revised_vote_digests: tuple[str, ...]
    disputed_fields: tuple[str, ...]
    outcome: CouncilOutcome
    reason_codes: tuple[str, ...]
    rounds: int

    def __post_init__(self) -> None:
        if len(self.model_digests) != 3 or len(self.initial_vote_digests) != 3:
            raise ValueError("council receipt MUST contain three models and initial votes")
        for digest in (
            self.claim_digest,
            self.packet_digest,
            self.policy_digest,
            *self.model_digests,
            *self.initial_vote_digests,
            *self.revised_vote_digests,
        ):
            if _DIGEST.fullmatch(digest) is None:
                raise ValueError("council receipt digest MUST be a lowercase SHA-256 digest")
        if len(set(self.model_digests)) != 3:
            raise ValueError("council receipt models MUST be distinct")
        if self.rounds not in {1, 2}:
            raise ValueError("council receipt rounds MUST be one or two")
        if self.rounds == 1 and self.revised_vote_digests:
            raise ValueError("single-round receipt MUST NOT contain revised votes")
        if self.rounds == 2 and len(self.revised_vote_digests) != 3:
            raise ValueError("two-round receipt MUST contain three revised votes")
        if len(self.disputed_fields) > 32 or len(set(self.disputed_fields)) != len(
            self.disputed_fields
        ):
            raise ValueError("council receipt disputed fields MUST be bounded and unique")
        if self.disputed_fields != tuple(sorted(self.disputed_fields)):
            raise ValueError("council receipt disputed fields MUST be sorted")
        if any(_PROPERTY.fullmatch(name) is None for name in self.disputed_fields):
            raise ValueError("council receipt disputed fields MUST use property syntax")
        if not self.reason_codes or len(self.reason_codes) > 16:
            raise ValueError("council receipt MUST contain bounded reason codes")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("council receipt reason codes MUST be unique and sorted")
        if any(_PROPERTY.fullmatch(reason) is None for reason in self.reason_codes):
            raise ValueError("council receipt reason code MUST use property syntax")


__all__ = ["CouncilOutcome", "OntologyCouncilReceipt"]
