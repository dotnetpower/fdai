"""Read-only FunctionType for the server-configured subscription identity."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

SUBSCRIPTION_SCOPE_FUNCTION_NAME = "query.subscription_scope_identity"
SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS = (
    "subscription.display_name",
    "subscription.state",
    "subscription.observed_at",
)
SUBSCRIPTION_SCOPE_STATES = frozenset({"Deleted", "Disabled", "Enabled", "PastDue", "Warned"})
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_MASKED_ID = re.compile(r"^[a-f0-9]{4}\.\.\.[a-f0-9]{4}$")


@dataclass(frozen=True, slots=True)
class SubscriptionScopeObservation:
    """Sanitized identity facts observed for one configured subscription."""

    display_name: str
    state: str
    masked_subscription_id: str
    observed_at: datetime
    evidence_digest: str

    def __post_init__(self) -> None:
        if (
            not self.display_name.strip()
            or len(self.display_name) > 256
            or any(ord(char) < 32 for char in self.display_name)
        ):
            raise ValueError("subscription display_name MUST be bounded and printable")
        if self.state not in SUBSCRIPTION_SCOPE_STATES:
            raise ValueError("subscription state MUST be a reviewed Azure state")
        if not _MASKED_ID.fullmatch(self.masked_subscription_id):
            raise ValueError("masked_subscription_id MUST retain only four boundary characters")
        if self.observed_at.tzinfo is None:
            raise ValueError("subscription observed_at MUST be timezone-aware")
        if not _DIGEST.fullmatch(self.evidence_digest):
            raise ValueError("subscription evidence_digest MUST be a SHA-256 reference")


@dataclass(frozen=True, slots=True)
class SubscriptionScopeCollection:
    """One verified observation or an explicit provider limitation."""

    observation: SubscriptionScopeObservation | None
    observed_at: datetime
    complete: bool
    limitation: str | None
    attempt_ref: str

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("subscription collection time MUST be timezone-aware")
        if self.complete != (self.observation is not None):
            raise ValueError("complete subscription collection requires exactly one observation")
        if self.complete == (self.limitation is not None):
            raise ValueError("subscription completeness and limitation are inconsistent")
        if self.observation is not None and self.observation.observed_at != self.observed_at:
            raise ValueError("subscription observation time MUST match its collection")
        if not _DIGEST.fullmatch(self.attempt_ref):
            raise ValueError("subscription attempt_ref MUST be a SHA-256 reference")


class SubscriptionScopeReader(Protocol):
    """Read identity only for the composition-owned subscription."""

    async def read(self) -> SubscriptionScopeCollection: ...


def subscription_scope_function_type() -> OntologyFunctionType:
    """Declare the no-input server-scoped subscription identity read."""

    return OntologyFunctionType(
        name=SUBSCRIPTION_SCOPE_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "x-fdai-measure-concepts": list(SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS),
            "properties": {
                "rows": {"type": "array", "maxItems": 1},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=10,
        cpu_millis=100,
        memory_bytes=33_554_432,
        max_output_bytes=65_536,
        network_allowed=False,
        credentials_allowed=False,
    )


def subscription_scope_function(
    ontology_release: OntologyRelease,
    *,
    reader: SubscriptionScopeReader,
) -> ContextualOntologyFunction:
    """Project one sanitized subscription observation without accepting scope."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        SUBSCRIPTION_SCOPE_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("subscription scope purpose does not match invocation context")
        if arguments:
            raise ValueError("subscription scope identity accepts no caller arguments")
        collection = await reader.read()
        rows = (
            (
                QueryRow.from_values(
                    "subscription-scope",
                    {
                        "display_name": collection.observation.display_name,
                        "state": collection.observation.state,
                        "masked_subscription_id": collection.observation.masked_subscription_id,
                        "observed_at": collection.observation.observed_at.isoformat(),
                        "evidence_digest": collection.observation.evidence_digest,
                        "execution_authority": False,
                    },
                ),
            )
            if collection.observation is not None
            else ()
        )
        table = QueryTable(
            rows=rows,
            complete=collection.complete,
            truncation_reason=collection.limitation,
        )
        return cast(dict[str, object], json.loads(table.canonical_json()))

    return evaluate


__all__ = [
    "SUBSCRIPTION_SCOPE_FUNCTION_NAME",
    "SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS",
    "SUBSCRIPTION_SCOPE_STATES",
    "SubscriptionScopeCollection",
    "SubscriptionScopeObservation",
    "SubscriptionScopeReader",
    "subscription_scope_function",
    "subscription_scope_function_type",
]
