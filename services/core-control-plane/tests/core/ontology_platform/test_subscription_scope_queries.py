"""Server-scoped subscription identity FunctionType tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.subscription_scope_queries import (
    SUBSCRIPTION_SCOPE_FUNCTION_NAME,
    SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS,
    SubscriptionScopeCollection,
    SubscriptionScopeObservation,
    subscription_scope_function,
    subscription_scope_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release

NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)


class _Reader:
    def __init__(self, result: SubscriptionScopeCollection) -> None:
        self.result = result
        self.calls = 0

    async def read(self) -> SubscriptionScopeCollection:
        self.calls += 1
        return self.result


def _collection(*, available: bool = True) -> SubscriptionScopeCollection:
    return SubscriptionScopeCollection(
        observation=(
            SubscriptionScopeObservation(
                display_name="Example subscription",
                state="Enabled",
                masked_subscription_id="0000...0000",
                observed_at=NOW,
                evidence_digest=DIGEST,
            )
            if available
            else None
        ),
        observed_at=NOW,
        complete=available,
        limitation=None if available else "source_unavailable",
        attempt_ref="sha256:" + ("b" * 64),
    )


async def _invoke(
    reader: _Reader,
    *,
    arguments: dict[str, object] | None = None,
    purpose: str = "operations-review",
) -> dict[str, object]:
    declaration = subscription_scope_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        subscription_scope_function(release, reader=reader),
    )
    result = await registry.invoke(
        SUBSCRIPTION_SCOPE_FUNCTION_NAME,
        arguments or {},
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=(purpose,),
        ),
    )
    assert isinstance(result, dict)
    return result


def test_subscription_scope_function_is_no_input_and_read_only() -> None:
    declaration = subscription_scope_function_type()

    assert declaration.input_schema["properties"] == {}
    assert declaration.output_schema["x-fdai-measure-concepts"] == list(
        SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS
    )
    assert declaration.required_role is CeilingRole.READER
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False


async def test_subscription_scope_function_projects_sanitized_identity() -> None:
    reader = _Reader(_collection())

    result = await _invoke(reader)

    assert result == {
        "complete": True,
        "rows": [
            {
                "row_id": "subscription-scope",
                "values": {
                    "display_name": "Example subscription",
                    "evidence_digest": DIGEST,
                    "execution_authority": False,
                    "masked_subscription_id": "0000...0000",
                    "observed_at": NOW.isoformat(),
                    "state": "Enabled",
                },
            }
        ],
        "truncation_reason": None,
    }
    assert reader.calls == 1


async def test_subscription_scope_function_preserves_unavailable_result() -> None:
    result = await _invoke(_Reader(_collection(available=False)))

    assert result == {
        "complete": False,
        "rows": [],
        "truncation_reason": "source_unavailable",
    }


async def test_subscription_scope_function_rejects_scope_arguments_and_wrong_purpose() -> None:
    reader = _Reader(_collection())

    with pytest.raises(ValueError, match="arguments violate input_schema"):
        await _invoke(reader, arguments={"subscription_id": "caller-value"})
    with pytest.raises(PermissionError, match="purpose"):
        await _invoke(reader, purpose="deployment")
    assert reader.calls == 0
