"""Verify one immutable resolved-model revision before Operator startup."""

from __future__ import annotations

import hashlib
import hmac
import json
from asyncio import to_thread
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ResolvedModelsArtifact(Protocol):
    """Expose immutable resolved-model content and its source digest."""

    @property
    def content(self) -> str: ...

    @property
    def digest(self) -> str: ...

    @property
    def secret_version(self) -> str | None: ...


class AsyncResolvedModelsSource(Protocol):
    """Load one immutable revision."""

    async def load(self) -> ResolvedModelsArtifact: ...


@dataclass(frozen=True, slots=True)
class ConfiguredResolvedModelsArtifact:
    """Carry one file or inline revision."""

    content: str
    digest: str
    secret_version: str | None = None


@dataclass(frozen=True, slots=True)
class ConfiguredResolvedModelsSource:
    """Load the existing inline or mounted-file Operator binding."""

    path_or_content: str
    maximum_bytes: int = 1_048_576

    async def load(self) -> ConfiguredResolvedModelsArtifact:
        if self.path_or_content.lstrip().startswith("{"):
            content = self.path_or_content
        else:
            content = await to_thread(
                Path(self.path_or_content).read_text,
                encoding="utf-8",
            )
        encoded = content.encode("utf-8")
        if len(encoded) > self.maximum_bytes:
            raise ValueError("Operator resolved-model artifact exceeds the size limit")
        return ConfiguredResolvedModelsArtifact(
            content=content,
            digest=hashlib.sha256(encoded).hexdigest(),
        )


@dataclass(slots=True)
class OperatorResolvedModelsRevisionOwner:
    """Own source loading and the startup digest fence."""

    source: AsyncResolvedModelsSource
    expected_digest: str
    close: Callable[[], Awaitable[None]] | None = None
    revision: ResolvedModelsArtifact | None = None

    async def start(self) -> None:
        """Load exactly once and reject mismatch before later services start."""

        if self.revision is not None:
            return
        revision = await self.source.load()
        if not hmac.compare_digest(revision.digest, self.expected_digest):
            raise ValueError(
                "Operator resolved-model source revision does not match deployment binding"
            )
        try:
            payload = json.loads(revision.content)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("Operator resolved-model startup artifact is invalid") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("capabilities"), list):
            raise ValueError("Operator resolved-model startup artifact is invalid")
        self.revision = revision

    async def aclose(self) -> None:
        """Close composition-owned source resources."""

        if self.close is not None:
            await self.close()


__all__ = [
    "AsyncResolvedModelsSource",
    "ConfiguredResolvedModelsSource",
    "OperatorResolvedModelsRevisionOwner",
    "ResolvedModelsArtifact",
]
