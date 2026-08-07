"""Provider-neutral contracts for request-local conversation backends."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

ContentPolicyStage = Literal["input", "output", "history_compaction", "unknown"]


class ChatContentPolicyError(Exception):
    """A non-retryable provider content-policy decision with no copied body."""

    def __init__(self, *, stage: ContentPolicyStage = "unknown") -> None:
        self.stage = stage
        super().__init__("chat request blocked by content policy")


class ChatBackend(Protocol):
    """Answer one validated conversation turn without transport authority."""

    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]: ...


@runtime_checkable
class ChatBackendMetadata(Protocol):
    """Optional public metadata exposed by provider adapters to the router."""

    @property
    def endpoint(self) -> str:
        """Return the configured provider endpoint without credentials."""
        ...

    @property
    def mode(self) -> str:
        """Return the public provider mode label."""
        ...

    @property
    def model(self) -> str:
        """Return the configured model or deployment name."""
        ...


class ChatBackendUnavailableError(Exception):
    """Raised by a backend when no upstream narrator is configured."""


class DisabledChatBackend:
    """No-op backend used when no narrator provider is configured."""

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002 - required by Protocol
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, Any]:
        raise ChatBackendUnavailableError("no chat backend configured")
