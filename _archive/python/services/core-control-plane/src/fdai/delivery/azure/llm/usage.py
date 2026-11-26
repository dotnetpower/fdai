"""Parse the ``usage`` object from an OpenAI / Azure OpenAI response.

``chat/completions`` (and the embeddings API) return a ``usage`` object
carrying ``prompt_tokens`` / ``completion_tokens``. :func:`extract_usage`
turns that into a :class:`~fdai.core.metering.usage.TokenUsage`, or
``None`` when the field is absent or malformed.

Metering is best-effort: this helper never raises. A missing or garbled
``usage`` yields ``None`` (the caller then records nothing) so a
provider that omits usage can never break the model call. It is a
delivery-layer adapter helper - ``core/`` stays free of wire shapes.
"""

from __future__ import annotations

from collections.abc import Mapping

from fdai.core.metering.usage import TokenUsage


def _non_negative_int(value: object) -> int | None:
    """Return ``value`` when it is a non-negative, non-boolean int, else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def extract_usage(envelope: object) -> TokenUsage | None:
    """Pull a :class:`TokenUsage` out of a chat/completions envelope.

    Returns ``None`` unless ``envelope['usage']`` is a mapping carrying
    non-negative integer ``prompt_tokens`` and ``completion_tokens``.
    Embedding responses report ``prompt_tokens`` with a zero/absent
    completion count; an absent ``completion_tokens`` is treated as 0.
    """
    if not isinstance(envelope, Mapping):
        return None
    usage = envelope.get("usage")
    if not isinstance(usage, Mapping):
        return None
    prompt = _non_negative_int(usage.get("prompt_tokens"))
    if prompt is None:
        return None
    completion_raw = usage.get("completion_tokens", 0)
    completion = _non_negative_int(completion_raw)
    if completion is None:
        return None
    return TokenUsage(prompt_tokens=prompt, completion_tokens=completion)


__all__ = ["extract_usage"]
