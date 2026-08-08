"""AzureCliWorkloadIdentity - dev-mode WorkloadIdentity backed by ``az``."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fdai.delivery.azure.dev_workload_identity import (
    AsyncAzureCliWorkloadIdentity,
    AzureCliCredentialError,
    AzureCliWorkloadIdentity,
)
from fdai.shared.providers.workload_identity import IdentityToken


def _completed(
    stdout: str, *, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["az"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _valid_payload(expires_on: str = "2099-01-01T00:00:00+00:00") -> str:
    return json.dumps({"accessToken": "tok-abc", "expiresOn": expires_on})


class TestGetTokenSync:
    def test_returns_token_and_caches(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed(_valid_payload()),
        ) as run:
            first = wi.get_token_sync("https://cognitiveservices.azure.com/.default")
            second = wi.get_token_sync("https://cognitiveservices.azure.com/.default")
        assert first.token == "tok-abc"
        assert second.token == "tok-abc"
        # Cache hit on second call - subprocess.run called ONCE.
        assert run.call_count == 1

    def test_expired_cache_triggers_refetch(self) -> None:
        wi = AzureCliWorkloadIdentity(skew=timedelta(hours=1))
        # First token expires in 30 seconds - inside the 1h skew window,
        # so it is treated as stale immediately and refetched.
        soon = (datetime.now(tz=UTC) + timedelta(seconds=30)).isoformat()
        later = (datetime.now(tz=UTC) + timedelta(hours=24)).isoformat()
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            side_effect=[
                _completed(_valid_payload(expires_on=soon)),
                _completed(json.dumps({"accessToken": "tok-fresh", "expiresOn": later})),
            ],
        ) as run:
            wi.get_token_sync("s")
            second = wi.get_token_sync("s")
        assert second.token == "tok-fresh"
        assert run.call_count == 2

    def test_epoch_expiry_wins_over_local_display_and_triggers_refetch(self) -> None:
        wi = AzureCliWorkloadIdentity(skew=timedelta())
        expired_epoch = int((datetime.now(tz=UTC) - timedelta(minutes=1)).timestamp())
        later = int((datetime.now(tz=UTC) + timedelta(hours=1)).timestamp())
        stale_payload = json.dumps(
            {
                "accessToken": "tok-stale",
                "expiresOn": "2099-01-01 00:00:00.000000",
                "expires_on": expired_epoch,
            }
        )
        fresh_payload = json.dumps(
            {
                "accessToken": "tok-fresh",
                "expiresOn": "2099-01-01 00:00:00.000000",
                "expires_on": later,
            }
        )
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            side_effect=[_completed(stale_payload), _completed(fresh_payload)],
        ) as run:
            first = wi.get_token_sync("s")
            second = wi.get_token_sync("s")

        assert first.token == "tok-stale"
        assert second.token == "tok-fresh"
        assert run.call_count == 2

    def test_empty_audience_rejected(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with pytest.raises(ValueError, match="audience MUST NOT be empty"):
            wi.get_token_sync("")

    def test_non_zero_exit_raises_credential_error(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed(
                "",
                returncode=1,
                stderr="Please run 'az login' to setup account.",
            ),
        ):
            with pytest.raises(AzureCliCredentialError, match="exited with code 1"):
                wi.get_token_sync("s")

    def test_missing_executable_raises_credential_error(self) -> None:
        wi = AzureCliWorkloadIdentity(executable="/no/such/az")
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            with pytest.raises(AzureCliCredentialError, match="not found on PATH"):
                wi.get_token_sync("s")

    def test_timeout_raises_credential_error(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="az", timeout=30),
        ):
            with pytest.raises(AzureCliCredentialError, match="timed out"):
                wi.get_token_sync("s")

    def test_non_json_stdout_raises_credential_error(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed("not-json"),
        ):
            with pytest.raises(AzureCliCredentialError, match="non-JSON"):
                wi.get_token_sync("s")

    def test_missing_access_token_raises_credential_error(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed(json.dumps({"expiresOn": "2099-01-01T00:00:00Z"})),
        ):
            with pytest.raises(AzureCliCredentialError, match="missing accessToken"):
                wi.get_token_sync("s")

    def test_missing_expires_on_raises_credential_error(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed(json.dumps({"accessToken": "x"})),
        ):
            with pytest.raises(AzureCliCredentialError, match="missing expiresOn"):
                wi.get_token_sync("s")

    def test_naive_datetime_string_parsed_as_local_time(self) -> None:
        """Older az CLI: ``expiresOn: '2099-01-01 00:00:00.000000'``."""
        wi = AzureCliWorkloadIdentity()
        payload = json.dumps(
            {
                "accessToken": "tok",
                "expiresOn": "2099-01-01 00:00:00.000000",
            }
        )
        original_tz = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "Asia/Seoul"
            time.tzset()
            with patch(
                "fdai.delivery.azure.dev_workload_identity.subprocess.run",
                return_value=_completed(payload),
            ):
                token = wi.get_token_sync("s")
        finally:
            if original_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original_tz
            time.tzset()
        assert token.expires_at == datetime(2098, 12, 31, 15, tzinfo=UTC)

    def test_iso_with_z_suffix_parsed(self) -> None:
        wi = AzureCliWorkloadIdentity()
        payload = json.dumps(
            {
                "accessToken": "tok",
                "expiresOn": "2099-01-01T00:00:00Z",
            }
        )
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed(payload),
        ):
            token = wi.get_token_sync("s")
        assert token.expires_at.tzinfo is UTC

    def test_msal_default_suffix_stripped_before_shelling(self) -> None:
        """`az account get-access-token --resource` rejects the MSAL
        `.default` scope form; the adapter MUST strip it so callers
        can pass the same audience they would to a Managed-Identity
        adapter.
        """
        wi = AzureCliWorkloadIdentity()
        captured: dict[str, list[str]] = {}

        def _side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
            captured["argv"] = list(args[0])
            return _completed(_valid_payload())

        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            side_effect=_side_effect,
        ):
            wi.get_token_sync("https://cognitiveservices.azure.com/.default")

        argv = captured["argv"]
        assert "--resource" in argv
        resource = argv[argv.index("--resource") + 1]
        assert resource == "https://cognitiveservices.azure.com"

    def test_from_env_prefers_subscription_for_account_pinning(self) -> None:
        wi = AzureCliWorkloadIdentity.from_env(
            {
                "AZURE_SUBSCRIPTION_ID": "subscription-a",
                "AZURE_TENANT_ID": "tenant-a",
            }
        )
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed(_valid_payload()),
        ) as run:
            wi.get_token_sync("https://example.servicebus.windows.net/.default")

        command = run.call_args.args[0]
        assert command[command.index("--subscription") + 1] == "subscription-a"
        assert "--tenant" not in command

    def test_from_env_uses_tenant_when_subscription_is_absent(self) -> None:
        wi = AzureCliWorkloadIdentity.from_env({"AZURE_TENANT_ID": "tenant-a"})
        with patch(
            "fdai.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed(_valid_payload()),
        ) as run:
            wi.get_token_sync("https://example.servicebus.windows.net/.default")

        command = run.call_args.args[0]
        assert "--subscription" not in command
        assert command[command.index("--tenant") + 1] == "tenant-a"


async def test_async_adapter_returns_cli_token() -> None:
    credential = AzureCliWorkloadIdentity()
    adapter = AsyncAzureCliWorkloadIdentity(credential=credential)
    expected = IdentityToken(
        token="graph-token",
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        audience="https://graph.microsoft.com/.default",
    )
    with patch.object(
        AzureCliWorkloadIdentity,
        "get_token_sync",
        return_value=expected,
    ) as get_token:
        result = await adapter.get_token("https://graph.microsoft.com/.default")

    assert result is expected
    get_token.assert_called_once_with("https://graph.microsoft.com/.default")
