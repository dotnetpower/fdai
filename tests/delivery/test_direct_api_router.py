from __future__ import annotations

from uuid import UUID

import pytest

from fdai.delivery.direct_api_router import RoutedDirectApiExecutor
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiPreconditionError,
    DirectApiRequest,
)
from fdai.shared.providers.testing.direct_api import RecordingDirectApiExecutor


def _request(identity_ref: str | None) -> DirectApiRequest:
    metadata = {"executor_identity_ref": identity_ref} if identity_ref is not None else {}
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="request-1",
        action_type_name="ops.restart-service",
        rule_ids=("rule-1",),
        resource_ref="resource-1",
        labels=("shadow",),
        mode=Mode.SHADOW,
        metadata=metadata,
    )


async def test_router_selects_authorized_identity_adapter() -> None:
    change = RecordingDirectApiExecutor()
    fallback = RecordingDirectApiExecutor()
    router = RoutedDirectApiExecutor(
        routes={},
        identity_routes={"identity/change": change},
        fallback=fallback,
    )

    await router.execute(_request("identity/change"))

    assert len(change.records) == 1
    assert fallback.records == ()


async def test_router_rejects_unknown_authorized_identity() -> None:
    router = RoutedDirectApiExecutor(
        routes={},
        identity_routes={"identity/change": RecordingDirectApiExecutor()},
        fallback=RecordingDirectApiExecutor(),
    )

    with pytest.raises(DirectApiPreconditionError, match="executor identity"):
        await router.execute(_request("identity/unknown"))
