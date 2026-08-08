"""Token-usage value object for LLM metering.

A :class:`TokenUsage` is the measured (never estimated) prompt +
completion token count reported by a provider's ``chat/completions``
response ``usage`` object. The control plane records the measured value
so a cost report is grounded in real spend, honouring the
measurement-first rule in ``docs/roadmap/architecture/goals-and-metrics.md``.

The type is a frozen, addable value object so many per-call usages roll
up into a per-conversation / per-day / per-month total without mutation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Prompt + completion token counts for one LLM invocation.

    Both fields are non-negative integers. ``total_tokens`` is derived,
    never stored, so a provider that reports a mismatched total cannot
    desync the two halves from their sum.
    """

    prompt_tokens: int
    completion_tokens: int

    def __post_init__(self) -> None:
        if self.prompt_tokens < 0:
            raise ValueError("prompt_tokens MUST be >= 0")
        if self.completion_tokens < 0:
            raise ValueError("completion_tokens MUST be >= 0")

    @property
    def total_tokens(self) -> int:
        """Sum of prompt and completion tokens."""
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """Roll two usages into one aggregate (component-wise sum)."""
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )

    @classmethod
    def zero(cls) -> TokenUsage:
        """The additive identity - a starting accumulator for ``sum``-style rollups."""
        return cls(prompt_tokens=0, completion_tokens=0)


__all__ = ["TokenUsage"]
