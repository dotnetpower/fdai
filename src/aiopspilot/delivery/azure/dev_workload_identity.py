"""AzureCliWorkloadIdentity - dev-only WorkloadIdentity backed by ``az`` CLI.

Shells out to ``az account get-access-token --resource <scope>`` and
returns the resulting token as an
:class:`~aiopspilot.shared.providers.workload_identity.IdentityToken`.

Intended use
------------
The operator console CLI (``tools/chat.py``) runs on a developer
workstation where the operator has already run ``az login``. This
adapter piggybacks on that credential so the CLI can call Azure
OpenAI (or any other Azure data plane) without the operator
provisioning a Managed Identity.

Prod paths MUST use
:class:`~aiopspilot.delivery.azure.workload_identity.ManagedIdentityWorkloadIdentity`
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

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from aiopspilot.shared.providers.workload_identity import IdentityToken

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
    :class:`~aiopspilot.shared.providers.workload_identity.WorkloadIdentity`
    Protocol - callers that need async MUST wrap the sync
    :meth:`get_token_sync` themselves. The narrator CLI keeps
    everything sync.
    """

    executable: str = "az"
    skew: timedelta = _DEFAULT_SKEW
    _cache: dict[str, _CacheEntry] = field(default_factory=dict, init=False)

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
        try:
            proc = subprocess.run(  # noqa: S603 - executable path validated + timeout enforced
                [
                    self.executable,
                    "account",
                    "get-access-token",
                    "--resource",
                    resource,
                    "--output",
                    "json",
                ],
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
        expires_on = payload.get("expiresOn") or payload.get("expires_on")
        if not isinstance(access_token, str) or not access_token:
            raise AzureCliCredentialError("az CLI payload missing accessToken")
        if not isinstance(expires_on, str) or not expires_on:
            raise AzureCliCredentialError("az CLI payload missing expiresOn")

        expires_at = _parse_expires_on(expires_on)
        return IdentityToken(
            token=access_token,
            expires_at=expires_at,
            audience=audience,
        )


def _parse_expires_on(raw: str) -> datetime:
    """Parse the several formats ``az`` can emit for ``expiresOn``.

    Newer versions emit ISO 8601 with a timezone; older versions emit
    the local naive form ``"YYYY-MM-DD HH:MM:SS.mmmmmm"``. Assume UTC
    when no zone is present - the token is opaque to us, we only need
    a monotonic comparison against ``datetime.now(tz=UTC)``.
    """
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        # Old CLI: "2026-07-07 12:34:56.000000"
        parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


__all__ = ["AzureCliCredentialError", "AzureCliWorkloadIdentity"]
