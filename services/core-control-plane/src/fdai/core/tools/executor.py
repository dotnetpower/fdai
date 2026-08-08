"""Tool dispatch executor for the T2 tier.

Wave 2.5-B step 2a introduces the :class:`ToolExecutor` async Protocol,
its upstream default implementation, and the :class:`ToolProvider`
seam. Wave 2.5-B step 2b wires the executor into the Azure OpenAI
cross-check adapter so a model-issued tool call actually reaches a
provider round-trip.

The executor is the deterministic gate that stands between the model
and any provider. It:

- looks up the :class:`ToolArtifact` in the registry (unknown ids fail
  closed),
- rejects any call whose tool is still marked ``default_mode: shadow``
  unless the caller opts in to shadow dispatch (production leaves it
  off, so a shadow tool that leaks into the model manifest still
  cannot cause any side effect),
- validates the model-issued arguments against the tool's
  ``input_schema`` (schema failures fail closed),
- resolves the tool's declared ``provider`` name against the injected
  provider mapping, and
- wraps the provider result in the artifact's ``output_wrapper`` so
  the ``trusted="false"`` invariant is preserved on the next model
  turn.

Every failure path raises a subclass of :class:`ToolExecutorError` so
callers can route to HIL without swallowing the underlying reason.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from jsonschema import Draft202012Validator

from fdai.core.prompts.types import PromptMode
from fdai.core.tools.registry import ToolRegistry
from fdai.core.tools.types import ToolArtifact

_WRAPPER_PLACEHOLDER: Final[str] = "{}"
_DEFAULT_WRAPPER: Final[str] = (
    '<tool_result trusted="false" tool="{tool_id}">{payload}</tool_result>'
)


# ---------------------------------------------------------------------------
# Result + errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Everything a caller needs to feed the next model turn.

    ``wrapped_text`` is the string to inject verbatim into the next
    prompt. ``raw`` is the provider's return value so a downstream
    audit writer can serialize it separately. ``cost_usd`` and
    ``latency_ms`` are recorded so the debate orchestrator (Wave 4.5)
    can enforce per-event budgets.
    """

    tool_id: str
    wrapped_text: str
    raw: object
    cost_usd: float
    latency_ms: int


class ToolExecutorError(RuntimeError):
    """Base class for every fail-closed executor outcome.

    Every subclass carries the ``tool_id`` for audit correlation. The
    caller MUST route to HIL rather than treating the error as a
    fallback; the executor never returns a partial result.
    """

    def __init__(self, tool_id: str, message: str) -> None:
        self.tool_id: Final[str] = tool_id
        super().__init__(f"tool {tool_id!r}: {message}")


class UnknownToolError(ToolExecutorError):
    """The model called a tool id that is not in the registry."""


class ShadowToolBlockedError(ToolExecutorError):
    """The tool is still ``default_mode: shadow`` and the executor is not
    opted in to shadow dispatch. The prompt-manifest layer should have
    filtered the tool out in production; this guard is the belt behind
    that filter.
    """


class ToolArgumentValidationError(ToolExecutorError):
    """The model-issued arguments failed the tool's ``input_schema``.

    Fail-closed: a malformed argument means the executor never reaches
    a provider, so injection through argument text cannot smuggle a
    side effect.
    """


class MissingProviderError(ToolExecutorError):
    """The tool declared a ``provider`` name that is not wired.

    Reaching this error in production means either the fork forgot to
    register the provider or the tool YAML is out of sync with the
    composition root. Both are configuration defects worth surfacing
    loudly.
    """


class ProviderCallError(ToolExecutorError):
    """The registered provider raised while handling the call.

    The original exception is available as ``__cause__`` for the
    audit writer; the executor never swallows the traceback.
    """


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class ToolProvider(Protocol):
    """Concrete backend for one or more tool ids.

    The executor maps a :class:`ToolArtifact.provider` string to one
    :class:`ToolProvider` instance at composition time. The provider
    is invoked with the already-validated arguments and a copy of the
    resolved artifact so it can decide whether to inspect metadata
    (e.g. capability_gate) without the executor pre-parsing everything.
    """

    async def call(
        self,
        *,
        artifact: ToolArtifact,
        arguments: Mapping[str, Any],
    ) -> object:
        """Execute the tool and return its raw result payload."""


class ToolExecutor(Protocol):
    """The seam :class:`fdai.delivery.azure.llm.cross_check`
    consumes to dispatch a single model-issued tool call.

    The Wave 2.5-B step 2a Protocol handles one call at a time. Batch
    dispatch (parallel tool calls in one model turn) lands in Wave
    2.5-B step 2b together with the OpenAI function-calling wire-up.
    """

    async def dispatch(
        self,
        *,
        tool_id: str,
        arguments: Mapping[str, Any],
    ) -> ToolResult:
        """Dispatch one call and return its wrapped result.

        MUST raise :class:`ToolExecutorError` on any failure so the
        caller can route to HIL; MUST NOT return a placeholder result.
        """


# ---------------------------------------------------------------------------
# Default implementation
# ---------------------------------------------------------------------------


class DefaultToolExecutor(ToolExecutor):
    """Upstream default: registry lookup + schema validation + provider dispatch.

    ``providers`` is a mapping from :class:`ToolArtifact.provider`
    (the string authored in the tool YAML) to a concrete
    :class:`ToolProvider`. Multiple tools MAY share a provider by
    declaring the same name; a fork picks its own provider names.

    ``allow_shadow_dispatch`` defaults to ``False`` so production runs
    can never accidentally execute a shadow tool. Evaluation harnesses
    that need to time provider round-trips against a shadow tool flip
    it on explicitly.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        providers: Mapping[str, ToolProvider],
        allow_shadow_dispatch: bool = False,
    ) -> None:
        self._registry: Final[ToolRegistry] = registry
        # Copy so a mutation of the caller's dict cannot swap a
        # provider under the executor's feet at runtime.
        self._providers: Final[Mapping[str, ToolProvider]] = dict(providers)
        self._allow_shadow_dispatch: Final[bool] = allow_shadow_dispatch

    async def dispatch(
        self,
        *,
        tool_id: str,
        arguments: Mapping[str, Any],
    ) -> ToolResult:
        try:
            artifact = self._registry.get(tool_id)
        except LookupError as exc:
            raise UnknownToolError(tool_id, "not in tool catalog") from exc

        if artifact.default_mode is PromptMode.SHADOW and not self._allow_shadow_dispatch:
            raise ShadowToolBlockedError(
                tool_id,
                "tool is 'default_mode: shadow' and executor is not opted in to shadow dispatch",
            )

        _validate_arguments(artifact, arguments)

        provider_name = artifact.provider
        if provider_name is None or provider_name not in self._providers:
            raise MissingProviderError(
                tool_id,
                f"no provider registered for name {provider_name!r}",
            )
        provider = self._providers[provider_name]

        started_at = time.monotonic()
        try:
            raw = await provider.call(artifact=artifact, arguments=arguments)
        except Exception as exc:  # noqa: BLE001 - fail-closed rethrow with cause
            raise ProviderCallError(tool_id, "provider raised") from exc
        latency_ms = int((time.monotonic() - started_at) * 1000)

        wrapped = _wrap_output(artifact, raw)
        cost_usd = float(artifact.capability_gate.cost_budget_usd_per_call or 0.0)
        return ToolResult(
            tool_id=tool_id,
            wrapped_text=wrapped,
            raw=raw,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_arguments(artifact: ToolArtifact, arguments: Mapping[str, Any]) -> None:
    """Fail closed on any schema violation."""

    validator = Draft202012Validator(dict(artifact.input_schema))
    errors = sorted(validator.iter_errors(dict(arguments)), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    # Surface the first violation - the model will retry with the
    # correction and additional errors would land in the next turn.
    first = errors[0]
    pointer = "/".join(str(p) for p in first.absolute_path) or "<root>"
    raise ToolArgumentValidationError(
        artifact.id,
        f"arguments violate input_schema at {pointer}: {first.message}",
    )


def _wrap_output(artifact: ToolArtifact, raw: object) -> str:
    """Render the provider payload inside the tool's declared wrapper.

    ``output_wrapper`` MUST contain the literal placeholder ``{}``
    which the executor replaces with the payload. When the tool YAML
    omits ``output_wrapper``, the executor falls back to a canonical
    envelope so the ``trusted="false"`` invariant still holds.
    """

    payload = _render_payload(raw)
    wrapper = artifact.output_wrapper
    if wrapper is None:
        return _DEFAULT_WRAPPER.format(tool_id=artifact.id, payload=payload)
    if _WRAPPER_PLACEHOLDER not in wrapper:
        raise ToolExecutorError(
            artifact.id,
            "output_wrapper MUST contain the '{}' placeholder for the payload",
        )
    return wrapper.replace(_WRAPPER_PLACEHOLDER, payload, 1)


def _render_payload(raw: object) -> str:
    """Turn the provider payload into a stable string.

    Strings pass through so a provider can hand back pre-formatted
    text (useful for RAG-style results). Non-string values are
    rendered via :func:`json.dumps` so structured data lands in the
    prompt as valid JSON the model can parse.
    """

    if isinstance(raw, str):
        return raw
    import json

    return json.dumps(raw, sort_keys=True, ensure_ascii=False)


__all__ = [
    "DefaultToolExecutor",
    "MissingProviderError",
    "ProviderCallError",
    "ShadowToolBlockedError",
    "ToolArgumentValidationError",
    "ToolExecutor",
    "ToolExecutorError",
    "ToolProvider",
    "ToolResult",
    "UnknownToolError",
]
