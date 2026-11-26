"""Coverage for security finding provider composition."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from fdai.shared.providers.projection import Finding
from fdai.shared.providers.security_findings import (
    CompositeSecurityFindingProvider,
    EmptySecurityFindingProvider,
    SecurityFindingProviderError,
)


class _Provider:
    def __init__(
        self,
        findings: tuple[Finding, ...] = (),
        error: SecurityFindingProviderError | None = None,
    ) -> None:
        self.findings = findings
        self.error = error
        self.calls: list[tuple[str, datetime | None, datetime | None]] = []

    async def collect(
        self,
        *,
        scope: str,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[Finding, ...]:
        self.calls.append((scope, since, until))
        if self.error is not None:
            raise self.error
        return self.findings


async def test_empty_provider_returns_no_findings() -> None:
    assert await EmptySecurityFindingProvider().collect(scope="example") == ()


async def test_composite_preserves_provider_order_and_window() -> None:
    first_finding = cast(Finding, object())
    second_finding = cast(Finding, object())
    first = _Provider((first_finding,))
    second = _Provider((second_finding,))
    since = datetime(2026, 8, 30, tzinfo=UTC)
    until = datetime(2026, 8, 31, tzinfo=UTC)

    result = await CompositeSecurityFindingProvider((first, second)).collect(
        scope="example",
        since=since,
        until=until,
    )

    assert result == (first_finding, second_finding)
    assert first.calls == second.calls == [("example", since, until)]


async def test_composite_propagates_child_error_instead_of_partial_result() -> None:
    first = _Provider((cast(Finding, object()),))
    failure = SecurityFindingProviderError("provider unavailable")
    second = _Provider(error=failure)

    with pytest.raises(SecurityFindingProviderError) as raised:
        await CompositeSecurityFindingProvider((first, second)).collect(scope="example")

    assert raised.value is failure
