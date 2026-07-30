"""AzureCliWorkloadIdentity - dev-only WorkloadIdentity backed by ``az`` CLI.

Shells out to ``az account get-access-token --resource <scope>`` and
returns the resulting token as an
:class:`~fdai.shared.providers.workload_identity.IdentityToken`.

Intended use
------------
The operator console CLI (``tools/chat.py``) runs on a developer
workstation where the operator has already run ``az login``. This
adapter piggybacks on that credential so the CLI can call Azure
OpenAI (or any other Azure data plane) without the operator
provisioning a Managed Identity.

Prod paths MUST use
:class:`~fdai.delivery.azure.workload_identity.ManagedIdentityWorkloadIdentity`
instead - shelling to ``az`` inside a container is a smell (extra
runtime dependency, blocks the event loop). This adapter is
deliberately non-async: the CLI already blocks per-turn.

Caching
-------
The ``az`` invocation is expensive (100-300 ms) so tokens are cached
per audience until 5 minutes before their reported ``expiresOn`` -
the same skew the Managed-Identity adapter uses.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from fdai.shared.providers.workload_identity import IdentityToken

_DEFAULT_SKEW: Final[timedelta] = timedelta(minutes=5)
_AZ_TIMEOUT_SECONDS: Final[float] = 30.0


class AzureCliCredentialError(RuntimeError):
    """Raised when ``az`` is missing, un-logged, or returns junk."""


@dataclass(slots=True)
class _CacheEntry:
    token: IdentityToken


@dataclass(slots=True)
class AzureCliWorkloadIdentity:
    """Sync :class:`WorkloadIdentity` adapter backed by ``az``.

    Not registered against the async
    :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
    Protocol - callers that need async MUST wrap the sync
    :meth:`get_token_sync` themselves. The narrator CLI keeps
    everything sync.
    """

    executable: str = "az"
    skew: timedelta = _DEFAULT_SKEW
    subscription_id: str | None = None
    tenant_id: str | None = None
    _cache: dict[str, _CacheEntry] = field(default_factory=dict, init=False)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> AzureCliWorkloadIdentity:
        """Bind token refreshes to the configured local runtime account."""

        env = os.environ if environ is None else environ
        return cls(
            subscription_id=env.get("AZURE_SUBSCRIPTION_ID", "").strip() or None,
            tenant_id=env.get("AZURE_TENANT_ID", "").strip() or None,
        )

    def get_token_sync(self, audience: str) -> IdentityToken:
        """Return a cached or freshly-fetched token for ``audience``."""

        if not audience:
            raise ValueError("audience MUST NOT be empty")

        cached = self._cache.get(audience)
        now = datetime.now(tz=UTC)
        if cached is not None and cached.token.expires_at - self.skew > now:
            return cached.token

        token = self._fetch(audience)
        self._cache[audience] = _CacheEntry(token=token)
        return token

    def _fetch(self, audience: str) -> IdentityToken:
        # `az account get-access-token --resource` expects an AAD
        # *resource URI* (e.g. https://cognitiveservices.azure.com),
        # NOT a scope with a `/.default` suffix (MSAL scope form).
        # Callers pass the scope form to line up with the Managed
        # Identity adapter; normalize here so the same audience works
        # against both backends.
        resource = audience[: -len("/.default")] if audience.endswith("/.default") else audience
        command = [
            self.executable,
            "account",
            "get-access-token",
            "--resource",
            resource,
            "--output",
            "json",
        ]
        if self.subscription_id is not None:
            command.extend(("--subscription", self.subscription_id))
        elif self.tenant_id is not None:
            command.extend(("--tenant", self.tenant_id))
        try:
            proc = subprocess.run(  # noqa: S603 - executable path validated + timeout enforced
                command,
                capture_output=True,
                text=True,
                timeout=_AZ_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AzureCliCredentialError(
                f"'{self.executable}' executable not found on PATH; install "
                "the Azure CLI or point AzureCliWorkloadIdentity(executable=...) "
                "at the right binary"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AzureCliCredentialError(
                f"'{self.executable} account get-access-token' timed out after "
                f"{_AZ_TIMEOUT_SECONDS}s"
            ) from exc

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            raise AzureCliCredentialError(
                f"az CLI exited with code {proc.returncode}: "
                f"{stderr[:400] if stderr else '(no stderr)'}. "
                "Run 'az login' or set AZURE_CONFIG_DIR to the right profile."
            )

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AzureCliCredentialError("az CLI returned non-JSON output") from exc

        access_token = payload.get("accessToken")
        # Modern Azure CLI emits both fields: ``expires_on`` is an absolute
        # Unix timestamp, while ``expiresOn`` is a display string in local
        # time. Prefer the timestamp so a long-running process never extends
        # a token's cache lifetime by the workstation's UTC offset.
        expires_on = payload.get("expires_on")
        if not isinstance(expires_on, (str, int, float)) or isinstance(expires_on, bool):
            expires_on = payload.get("expiresOn")
        if not isinstance(access_token, str) or not access_token:
            raise AzureCliCredentialError("az CLI payload missing accessToken")
        if (
            not isinstance(expires_on, (str, int, float))
            or isinstance(expires_on, bool)
            or expires_on == ""
        ):
            raise AzureCliCredentialError("az CLI payload missing expiresOn")

        expires_at = _parse_expires_on(expires_on)
        return IdentityToken(
            token=access_token,
            expires_at=expires_at,
            audience=audience,
        )


@dataclass(slots=True)
class AsyncAzureCliWorkloadIdentity:
    """Async local-dev adapter that keeps Azure CLI work off the event loop."""

    credential: AzureCliWorkloadIdentity = field(default_factory=AzureCliWorkloadIdentity)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> AsyncAzureCliWorkloadIdentity:
        return cls(credential=AzureCliWorkloadIdentity.from_env(environ))

    async def get_token(self, audience: str) -> IdentityToken:
        async with self._lock:
            return await asyncio.to_thread(self.credential.get_token_sync, audience)


def _parse_expires_on(raw: str | int | float) -> datetime:
    """Parse the several formats ``az`` can emit for ``expiresOn``.

    Newer versions expose the absolute ``expires_on`` Unix timestamp.
    Older versions expose ``expiresOn`` as ISO 8601 or the local naive
    form ``"YYYY-MM-DD HH:MM:SS.mmmmmm"``. A naive value MUST be treated
    as system local time; attaching UTC directly can keep an expired token
    cached for the workstation's UTC offset.
    """
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=UTC)
    stripped = raw.strip()
    if stripped.isdigit():
        return datetime.fromtimestamp(int(stripped), tz=UTC)
    try:
        parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
    except ValueError:
        # Old CLI: "2026-07-07 12:34:56.000000"
        parsed = datetime.strptime(stripped, "%Y-%m-%d %H:%M:%S.%f")
    if parsed.tzinfo is None:
        return parsed.astimezone(UTC)
    return parsed.astimezone(UTC)


__all__ = [
    "AsyncAzureCliWorkloadIdentity",
    "AzureCliCredentialError",
    "AzureCliWorkloadIdentity",
]
