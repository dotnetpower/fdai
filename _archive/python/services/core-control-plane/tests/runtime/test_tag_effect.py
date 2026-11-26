from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from fdai.runtime.tag_effect import build_default_tag_effect_bindings
from fdai.shared.providers.workload_identity import IdentityToken


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="reader-token",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


async def test_default_tag_effect_binds_subscription_without_gateway() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    ) as client:
        expected, observer = build_default_tag_effect_bindings(
            environment={"AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001"},
            governed_execution_enabled=True,
            expected_effect_provider=None,
            effect_observer=None,
            execution_identities=None,
            identity=_Identity(),
            http_client=client,
        )

    assert expected is not None
    assert observer is not None


async def test_default_tag_effect_preserves_injected_bindings() -> None:
    async def expected(_action):
        return None

    async def observe(_action, _expected):
        return None

    selected_expected, selected_observer = build_default_tag_effect_bindings(
        environment={"AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001"},
        governed_execution_enabled=True,
        expected_effect_provider=expected,
        effect_observer=observe,
        execution_identities=None,
        identity=_Identity(),
        http_client=None,
    )

    assert selected_expected is expected
    assert selected_observer is observe
