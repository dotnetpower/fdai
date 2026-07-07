"""AzureCliWorkloadIdentity - dev-mode WorkloadIdentity backed by ``az``."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from aiopspilot.delivery.azure.dev_workload_identity import (
    AzureCliCredentialError,
    AzureCliWorkloadIdentity,
)


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
            "aiopspilot.delivery.azure.dev_workload_identity.subprocess.run",
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
            "aiopspilot.delivery.azure.dev_workload_identity.subprocess.run",
            side_effect=[
                _completed(_valid_payload(expires_on=soon)),
                _completed(json.dumps({"accessToken": "tok-fresh", "expiresOn": later})),
            ],
        ) as run:
            wi.get_token_sync("s")
            second = wi.get_token_sync("s")
        assert second.token == "tok-fresh"
        assert run.call_count == 2

    def test_empty_audience_rejected(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with pytest.raises(ValueError, match="audience MUST NOT be empty"):
            wi.get_token_sync("")

    def test_non_zero_exit_raises_credential_error(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with patch(
            "aiopspilot.delivery.azure.dev_workload_identity.subprocess.run",
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
            "aiopspilot.delivery.azure.dev_workload_identity.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            with pytest.raises(AzureCliCredentialError, match="not found on PATH"):
                wi.get_token_sync("s")

    def test_timeout_raises_credential_error(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with patch(
            "aiopspilot.delivery.azure.dev_workload_identity.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="az", timeout=30),
        ):
            with pytest.raises(AzureCliCredentialError, match="timed out"):
                wi.get_token_sync("s")

    def test_non_json_stdout_raises_credential_error(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with patch(
            "aiopspilot.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed("not-json"),
        ):
            with pytest.raises(AzureCliCredentialError, match="non-JSON"):
                wi.get_token_sync("s")

    def test_missing_access_token_raises_credential_error(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with patch(
            "aiopspilot.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed(json.dumps({"expiresOn": "2099-01-01T00:00:00Z"})),
        ):
            with pytest.raises(AzureCliCredentialError, match="missing accessToken"):
                wi.get_token_sync("s")

    def test_missing_expires_on_raises_credential_error(self) -> None:
        wi = AzureCliWorkloadIdentity()
        with patch(
            "aiopspilot.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed(json.dumps({"accessToken": "x"})),
        ):
            with pytest.raises(AzureCliCredentialError, match="missing expiresOn"):
                wi.get_token_sync("s")

    def test_naive_datetime_string_parsed_as_utc(self) -> None:
        """Older az CLI: ``expiresOn: '2099-01-01 00:00:00.000000'``."""
        wi = AzureCliWorkloadIdentity()
        payload = json.dumps(
            {
                "accessToken": "tok",
                "expiresOn": "2099-01-01 00:00:00.000000",
            }
        )
        with patch(
            "aiopspilot.delivery.azure.dev_workload_identity.subprocess.run",
            return_value=_completed(payload),
        ):
            token = wi.get_token_sync("s")
        assert token.expires_at.tzinfo is UTC
        assert token.expires_at.year == 2099

    def test_iso_with_z_suffix_parsed(self) -> None:
        wi = AzureCliWorkloadIdentity()
        payload = json.dumps(
            {
                "accessToken": "tok",
                "expiresOn": "2099-01-01T00:00:00Z",
            }
        )
        with patch(
            "aiopspilot.delivery.azure.dev_workload_identity.subprocess.run",
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
            "aiopspilot.delivery.azure.dev_workload_identity.subprocess.run",
            side_effect=_side_effect,
        ):
            wi.get_token_sync("https://cognitiveservices.azure.com/.default")

        argv = captured["argv"]
        assert "--resource" in argv
        resource = argv[argv.index("--resource") + 1]
        assert resource == "https://cognitiveservices.azure.com"
