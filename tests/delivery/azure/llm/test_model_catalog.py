from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from fdai.delivery.azure.llm.model_catalog import (
    AzureCliGptModelCatalogReader,
    ModelCatalogUnavailableError,
)


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> str:
        call = tuple(argv)
        self.calls.append(call)
        if call[1:4] == ("cognitiveservices", "model", "list"):
            return json.dumps(
                [
                    {
                        "kind": "OpenAI",
                        "model": {
                            "name": "gpt-5.4",
                            "version": "2026-03-05",
                            "lifecycleStatus": "GenerallyAvailable",
                            "skus": [{"name": "GlobalStandard"}, {"name": "DataZoneStandard"}],
                        },
                    },
                    {
                        "kind": "OpenAI",
                        "model": {
                            "name": "gpt-5.3-chat",
                            "version": "2026-03-03",
                            "lifecycleStatus": "Deprecated",
                            "skus": [{"name": "GlobalStandard"}],
                        },
                    },
                ]
            )
        if call[1:4] == ("cognitiveservices", "usage", "list"):
            return json.dumps(
                [
                    {
                        "name": {"value": "OpenAI.GlobalStandard.gpt-5.4"},
                        "currentValue": 100,
                        "limit": 475,
                    },
                    {
                        "name": {"value": "OpenAI.DataZoneStandard.gpt-5.4"},
                        "currentValue": 0,
                        "limit": 30,
                    },
                ]
            )
        if call[1:4] == ("cognitiveservices", "account", "list"):
            return json.dumps(
                [
                    {"name": "oai-example", "resourceGroup": "rg-example"},
                ]
            )
        if call[1:5] == ("cognitiveservices", "account", "deployment", "list"):
            return json.dumps(
                [
                    {
                        "name": "gpt-5.4",
                        "properties": {
                            "model": {"name": "gpt-5.4"},
                            "provisioningState": "Succeeded",
                        },
                    }
                ]
            )
        raise AssertionError(f"unexpected command: {call!r}")


@pytest.mark.asyncio
async def test_combines_catalog_quota_and_deployments_and_caches() -> None:
    runner = _Runner()
    reader = AzureCliGptModelCatalogReader(
        region="koreacentral",
        account_name="oai-example",
        runner=runner,
    )

    first = await reader.snapshot()
    second = await reader.snapshot()
    refreshed = await reader.snapshot(force_refresh=True)

    assert first is second
    assert refreshed is not second
    assert len(runner.calls) == 8
    current, deprecated = first.models
    assert current.family == "gpt-5.4"
    assert current.deployments == ("gpt-5.4",)
    assert current.deployed is True
    assert current.provisionable is True
    assert current.skus[0].available_tpm == 30_000
    assert current.skus[1].available_tpm == 375_000
    assert deprecated.selectable is False


@pytest.mark.asyncio
async def test_fails_closed_when_account_is_missing() -> None:
    runner = _Runner()

    def missing_account(argv: Sequence[str]) -> str:
        if tuple(argv)[1:4] == ("cognitiveservices", "account", "list"):
            return "[]"
        return runner(argv)

    reader = AzureCliGptModelCatalogReader(
        region="koreacentral",
        account_name="oai-example",
        runner=missing_account,
    )

    with pytest.raises(ModelCatalogUnavailableError, match="not unique"):
        await reader.snapshot()


def test_rejects_unsafe_azure_names() -> None:
    with pytest.raises(ValueError, match="safe names"):
        AzureCliGptModelCatalogReader(region="korea central", account_name="oai-example")
