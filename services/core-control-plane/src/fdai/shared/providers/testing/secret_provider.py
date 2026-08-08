"""In-memory :class:`SecretProvider` for unit tests + debugger sessions.

Dict-backed, fail-closed on miss. Mirrors the security rules on the
Protocol: values MUST NOT appear in log lines or audit entries - callers
that pass a fake secret still need to redact.
"""

from __future__ import annotations

from collections.abc import Mapping

from fdai.shared.providers.secret_provider import (
    SecretNotFoundError,
    SecretProvider,
)


class InMemorySecretProvider(SecretProvider):
    """Static, dict-backed :class:`SecretProvider`."""

    def __init__(self, secrets: Mapping[str, str] | None = None) -> None:
        self._secrets: dict[str, str] = dict(secrets or {})

    async def get(self, name: str) -> str:
        if name not in self._secrets:
            raise SecretNotFoundError(name)
        return self._secrets[name]

    # ---- Test helper ---------------------------------------------------------

    def register(self, name: str, value: str) -> None:
        """Add a secret at test-setup time - never at runtime."""
        self._secrets[name] = value


__all__ = ["InMemorySecretProvider"]
