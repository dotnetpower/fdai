"""Content-free outcome receipts for ontology model council decisions."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum

_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_PROPERTY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class CouncilOutcome(StrEnum):
    CONSENSUS = "consensus"
    CONTESTED = "contested"
    UNSUPPORTED = "unsupported"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class CouncilModelReceipt:
    """Content-free model identity pinned to one council receipt."""

    publisher: str
    family: str
    version: str
    deployment: str
    binding: str
    fault_domain: str
    identity_digest: str

    def __post_init__(self) -> None:
        values = (
            self.publisher,
            self.family,
            self.version,
            self.deployment,
            self.binding,
            self.fault_domain,
        )
        if any(not value.strip() or len(value) > 256 for value in values):
            raise ValueError("council receipt model identity MUST be bounded and non-empty")
        expected = hashlib.sha256(
            json.dumps(
                {
                    "publisher": self.publisher,
                    "family": self.family,
                    "version": self.version,
                    "deployment": self.deployment,
                    "binding": self.binding,
                    "fault_domain": self.fault_domain,
                },
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if self.identity_digest != expected:
            raise ValueError("council receipt model identity digest MUST match its fields")


@dataclass(frozen=True, slots=True)
class CouncilInvocationReceipt:
    """Measured, content-free observations for one model invocation."""

    model_digest: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.model_digest) is None:
            raise ValueError("council invocation model digest MUST be a lowercase SHA-256")
        if (
            type(self.prompt_tokens) is not int
            or type(self.completion_tokens) is not int
            or self.prompt_tokens < 0
            or self.completion_tokens < 0
        ):
            raise ValueError("council invocation usage MUST contain non-negative integers")
        if (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, (int, float))
            or not math.isfinite(self.latency_ms)
            or self.latency_ms < 0.0
        ):
            raise ValueError("council invocation latency MUST be finite and non-negative")


@dataclass(frozen=True, slots=True)
class OntologyCouncilReceipt:
    """Replay evidence that excludes source text and model reasoning."""

    claim_digest: str
    packet_digest: str
    policy_digest: str
    prompt_digest: str
    schema_digest: str
    ontology_release: str
    models: tuple[CouncilModelReceipt, CouncilModelReceipt, CouncilModelReceipt]
    model_digests: tuple[str, str, str]
    initial_vote_digests: tuple[str, str, str]
    revised_vote_digests: tuple[str, ...]
    disputed_fields: tuple[str, ...]
    outcome: CouncilOutcome
    reason_codes: tuple[str, ...]
    rounds: int
    initial_invocations: tuple[
        CouncilInvocationReceipt,
        CouncilInvocationReceipt,
        CouncilInvocationReceipt,
    ] = field(compare=False)
    revised_invocations: tuple[CouncilInvocationReceipt, ...] = field(
        default=(),
        compare=False,
    )

    def __post_init__(self) -> None:
        if len(self.model_digests) != 3 or len(self.initial_vote_digests) != 3:
            raise ValueError("council receipt MUST contain three models and initial votes")
        for digest in (
            self.claim_digest,
            self.packet_digest,
            self.policy_digest,
            self.prompt_digest,
            self.schema_digest,
            self.ontology_release,
            *self.model_digests,
            *self.initial_vote_digests,
            *self.revised_vote_digests,
        ):
            if _DIGEST.fullmatch(digest) is None:
                raise ValueError("council receipt digest MUST be a lowercase SHA-256 digest")
        if len(set(self.model_digests)) != 3:
            raise ValueError("council receipt models MUST be distinct")
        if len(self.models) != 3:
            raise ValueError("council receipt MUST contain three model records")
        if tuple(item.identity_digest for item in self.models) != self.model_digests:
            raise ValueError("council receipt model records MUST match model digests")
        if tuple(item.model_digest for item in self.initial_invocations) != self.model_digests:
            raise ValueError("council receipt initial invocations MUST match model digests")
        if self.rounds not in {1, 2}:
            raise ValueError("council receipt rounds MUST be one or two")
        if self.rounds == 1 and self.revised_vote_digests:
            raise ValueError("single-round receipt MUST NOT contain revised votes")
        if self.rounds == 1 and self.revised_invocations:
            raise ValueError("single-round receipt MUST NOT contain revised invocations")
        if self.rounds == 2 and len(self.revised_vote_digests) != 3:
            raise ValueError("two-round receipt MUST contain three revised votes")
        if (
            self.rounds == 2
            and tuple(item.model_digest for item in self.revised_invocations) != self.model_digests
        ):
            raise ValueError("two-round receipt invocations MUST match model digests")
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


__all__ = [
    "CouncilInvocationReceipt",
    "CouncilModelReceipt",
    "CouncilOutcome",
    "OntologyCouncilReceipt",
]
