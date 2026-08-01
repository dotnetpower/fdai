"""Tests for the az CLI-backed resolver query adapters."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from fdai.delivery.azure.llm.resolver_queries import (
    AzureCliCatalogQuery,
    AzureCliPermissionQuery,
    AzureCliProvisionedCapacityQuery,
    AzureCliQuotaQuery,
    AzureCliResolverError,
)


class _CompletedProc:
    """Stand-in for subprocess.CompletedProcess with only the fields we read."""

    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeSubprocess:
    """Records az invocations and returns queued responses in order."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(
        self,
        argv: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
    ) -> Any:
        del capture_output, text, timeout, check
        self.calls.append(list(argv))
        if not self._responses:
            raise AssertionError(f"unexpected az invocation: {argv!r}")
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> _FakeSubprocess:
    fake = _FakeSubprocess(responses=[])
    monkeypatch.setattr("fdai.delivery.azure.llm.resolver_queries.subprocess.run", fake)
    return fake


class TestCatalogQuery:
    def test_returns_openai_families_and_caches_per_region(
        self, fake_subprocess: _FakeSubprocess
    ) -> None:
        fake_subprocess._responses = [
            _CompletedProc(
                returncode=0,
                stdout=json.dumps(["gpt-5.4-mini", "gpt-5-mini", "gpt-4o"]),
            ),
        ]
        catalog = AzureCliCatalogQuery()
        first = catalog.families_in_region("koreacentral")
        second = catalog.families_in_region("koreacentral")
        assert first == {"gpt-5.4-mini", "gpt-5-mini", "gpt-4o"}
        assert second == first
        # Cache means only one az invocation for the same region.
        assert len(fake_subprocess.calls) == 1
        argv = fake_subprocess.calls[0]
        assert argv[0] == "az"
        assert "koreacentral" in argv
        assert "--query" in argv

    def test_returns_empty_when_no_families(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [_CompletedProc(returncode=0, stdout="[]")]
        catalog = AzureCliCatalogQuery()
        assert catalog.families_in_region("koreacentral") == set()

    def test_raises_on_nonzero_exit(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [
            _CompletedProc(returncode=1, stdout="", stderr="not logged in")
        ]
        with pytest.raises(AzureCliResolverError, match="exited with code 1"):
            AzureCliCatalogQuery().families_in_region("koreacentral")

    def test_raises_on_missing_binary(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [FileNotFoundError()]
        with pytest.raises(AzureCliResolverError, match="not found on PATH"):
            AzureCliCatalogQuery().families_in_region("koreacentral")

    def test_raises_on_timeout(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [subprocess.TimeoutExpired(cmd="az", timeout=1)]
        with pytest.raises(AzureCliResolverError, match="timed out"):
            AzureCliCatalogQuery().families_in_region("koreacentral")

    def test_raises_on_non_json(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [_CompletedProc(returncode=0, stdout="not json")]
        with pytest.raises(AzureCliResolverError, match="non-JSON"):
            AzureCliCatalogQuery().families_in_region("koreacentral")

    def test_raises_on_non_array_json(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [
            _CompletedProc(returncode=0, stdout='{"unexpected": "shape"}')
        ]
        with pytest.raises(AzureCliResolverError, match="MUST return a JSON array"):
            AzureCliCatalogQuery().families_in_region("koreacentral")


class TestPermissionQuery:
    def test_non_empty_result_means_role_held(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [
            _CompletedProc(
                returncode=0,
                stdout=json.dumps([{"principalId": "00000000-0000-0000-0000-000000000001"}]),
            )
        ]
        assert AzureCliPermissionQuery().principal_has_cognitive_services_contributor(
            subscription_id="00000000-0000-0000-0000-000000000000",
            principal_object_id="00000000-0000-0000-0000-000000000001",
        )
        argv = fake_subprocess.calls[0]
        assert "role" in argv and "assignment" in argv
        assert "--scope" in argv
        # Scope wired correctly.
        scope_idx = argv.index("--scope")
        assert argv[scope_idx + 1].startswith("/subscriptions/")

    def test_empty_result_means_role_absent(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [_CompletedProc(returncode=0, stdout="[]")]
        assert not AzureCliPermissionQuery().principal_has_cognitive_services_contributor(
            subscription_id="00000000-0000-0000-0000-000000000000",
            principal_object_id="00000000-0000-0000-0000-000000000001",
        )

    def test_raises_on_nonzero_exit(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [_CompletedProc(returncode=2, stderr="forbidden")]
        with pytest.raises(AzureCliResolverError):
            AzureCliPermissionQuery().principal_has_cognitive_services_contributor(
                subscription_id="00000000-0000-0000-0000-000000000000",
                principal_object_id="00000000-0000-0000-0000-000000000001",
            )


class TestQuotaQuery:
    def test_parses_family_from_last_dotted_segment(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [
            _CompletedProc(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "currentValue": 40,
                            "limit": 240,
                            "name": {"value": "OpenAI.Standard.gpt-4o-mini"},
                        },
                        {
                            "currentValue": 0,
                            "limit": 200,
                            "name": {"value": "OpenAI.Standard.gpt-5.4-mini"},
                        },
                    ]
                ),
            )
        ]
        quota = AzureCliQuotaQuery()
        assert (
            quota.available_capacity_tpm(
                region="koreacentral", publisher="OpenAI", family="gpt-4o-mini"
            )
            == 200_000
        )
        # Second family name has an internal dot; rsplit on '.' still gives
        # the correct trailing family segment.
        assert (
            quota.available_capacity_tpm(
                region="koreacentral", publisher="OpenAI", family="gpt-5.4-mini"
            )
            == 200_000
        )

    def test_second_call_uses_region_cache(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [
            _CompletedProc(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "currentValue": 0,
                            "limit": 100_000,
                            "name": {"value": "OpenAI.Standard.gpt-4o-mini"},
                        }
                    ]
                ),
            )
        ]
        quota = AzureCliQuotaQuery()
        quota.available_capacity_tpm(
            region="koreacentral", publisher="OpenAI", family="gpt-4o-mini"
        )
        quota.available_capacity_tpm(
            region="koreacentral", publisher="OpenAI", family="gpt-4o-mini"
        )
        assert len(fake_subprocess.calls) == 1

    def test_missing_family_returns_zero(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [_CompletedProc(returncode=0, stdout="[]")]
        assert (
            AzureCliQuotaQuery().available_capacity_tpm(
                region="koreacentral", publisher="OpenAI", family="gpt-4o-mini"
            )
            == 0
        )

    def test_unparseable_entry_contributes_zero(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [
            _CompletedProc(
                returncode=0,
                stdout=json.dumps(
                    [
                        {"name": {"value": "OpenAI.Standard.gpt-4o-mini"}},  # no limit
                        "not a dict",
                        {"name": None, "limit": 100},
                        {
                            "currentValue": 50,
                            "limit": 100,
                            "name": {"value": "OpenAI.Standard.gpt-4o-mini"},
                        },
                    ]
                ),
            )
        ]
        assert (
            AzureCliQuotaQuery().available_capacity_tpm(
                region="koreacentral", publisher="OpenAI", family="gpt-4o-mini"
            )
            == 50_000  # 50 x 1K TPM, other entries dropped
        )

    def test_excludes_noninteractive_quota(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [
            _CompletedProc(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "currentValue": 0,
                            "limit": 1_000,
                            "name": {"value": "OpenAI.GlobalBatch.gpt-4.1-nano"},
                        },
                        {
                            "currentValue": 0,
                            "limit": 500,
                            "name": {"value": "OpenAI.GlobalStandard.gpt4.1-nano-finetune"},
                        },
                        {
                            "currentValue": 5,
                            "limit": 25,
                            "name": {"value": "OpenAI.GlobalStandard.gpt4.1-nano"},
                        },
                    ]
                ),
            )
        ]

        assert (
            AzureCliQuotaQuery().available_capacity_tpm(
                region="koreacentral", publisher="OpenAI", family="gpt-4.1-nano"
            )
            == 20_000
        )

    def test_raises_on_nonzero_exit(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [_CompletedProc(returncode=1, stderr="unauthorized")]
        with pytest.raises(AzureCliResolverError):
            AzureCliQuotaQuery().available_capacity_tpm(
                region="koreacentral", publisher="OpenAI", family="gpt-4o-mini"
            )


class TestProvisionedCapacityQuery:
    def test_queries_model_version_and_live_ptu_capacity(
        self, fake_subprocess: _FakeSubprocess
    ) -> None:
        fake_subprocess._responses = [
            _CompletedProc(returncode=0, stdout=json.dumps(["2024-08-06"])),
            _CompletedProc(
                returncode=0,
                stdout=json.dumps(
                    {
                        "value": [
                            {
                                "location": "koreacentral",
                                "properties": {
                                    "model": {
                                        "format": "OpenAI",
                                        "name": "gpt-4o",
                                        "version": "2024-08-06",
                                    },
                                    "skuName": "ProvisionedManaged",
                                    "availableCapacity": 30,
                                },
                            },
                            {
                                "location": "eastus",
                                "properties": {
                                    "model": {
                                        "format": "OpenAI",
                                        "name": "gpt-4o",
                                        "version": "2024-08-06",
                                    },
                                    "skuName": "ProvisionedManaged",
                                    "availableCapacity": 100,
                                },
                            },
                        ]
                    }
                ),
            ),
        ]
        query = AzureCliProvisionedCapacityQuery(
            subscription_id="00000000-0000-0000-0000-000000000000"
        )

        first = query.available_capacity_ptu(
            region="koreacentral",
            publisher="OpenAI",
            family="gpt-4o",
            sku="ProvisionedManaged",
        )
        second = query.available_capacity_ptu(
            region="koreacentral",
            publisher="OpenAI",
            family="gpt-4o",
            sku="ProvisionedManaged",
        )

        assert first == second == 30
        assert len(fake_subprocess.calls) == 2
        rest_call = fake_subprocess.calls[1]
        rest_url = rest_call[rest_call.index("--url") + 1]
        assert "modelCapacities" in rest_url
        assert "modelName=gpt-4o" in rest_url
        assert "modelVersion=2024-08-06" in rest_url

    def test_non_openai_publisher_returns_zero_without_cli(
        self, fake_subprocess: _FakeSubprocess
    ) -> None:
        query = AzureCliProvisionedCapacityQuery(
            subscription_id="00000000-0000-0000-0000-000000000000"
        )

        assert (
            query.available_capacity_ptu(
                region="koreacentral",
                publisher="Anthropic",
                family="claude-opus-4",
                sku="ProvisionedManaged",
            )
            == 0
        )
        assert fake_subprocess.calls == []

    def test_rejects_untrusted_pagination_link(self, fake_subprocess: _FakeSubprocess) -> None:
        fake_subprocess._responses = [
            _CompletedProc(returncode=0, stdout=json.dumps(["2024-08-06"])),
            _CompletedProc(
                returncode=0,
                stdout=json.dumps({"value": [], "nextLink": "https://untrusted.example.com/next"}),
            ),
        ]
        query = AzureCliProvisionedCapacityQuery(
            subscription_id="00000000-0000-0000-0000-000000000000"
        )

        with pytest.raises(AzureCliResolverError, match="nextLink"):
            query.available_capacity_ptu(
                region="koreacentral",
                publisher="OpenAI",
                family="gpt-4o",
                sku="ProvisionedManaged",
            )
