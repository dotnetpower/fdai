"""EnvSecretProvider - read secrets from a snapshotted mapping.

Realizes :class:`fdai.shared.providers.secret_provider.SecretProvider`.
The default constructor snapshots ``os.environ`` so a mutation after
startup cannot silently change the resolution - matches the invariant on
the config provider.

Never logs secret values.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from fdai.shared.providers.secret_provider import SecretNotFoundError


class EnvSecretProvider:
    """Fallback secret provider used in dev + tests.

    The prefix (default ``FDAI_SECRET_``) narrows the env-var
    surface so ordinary process env vars are not silently returned as
    secrets. A fork that maps additional aliases MAY provide an
    explicit ``env`` mapping and skip the prefix.
    """

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        prefix: str = "FDAI_SECRET_",
    ) -> None:
        if env is not None:
            self._env: Mapping[str, str] = dict(env)
        else:
            self._env = dict(os.environ)
        self._prefix = prefix

    async def get(self, name: str) -> str:
        # Try prefixed key first, then a direct hit for tests that pass a
        # bare env dict.
        prefixed = f"{self._prefix}{name.upper().replace('-', '_')}"
        for key in (prefixed, name):
            if key in self._env:
                return self._env[key]
        raise SecretNotFoundError(f"secret {name!r} is not defined in EnvSecretProvider")


__all__ = ["EnvSecretProvider"]
