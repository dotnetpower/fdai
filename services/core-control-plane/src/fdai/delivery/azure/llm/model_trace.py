"""Build bounded redacted observations for already-issued model calls."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter, OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

from pydantic import Field, model_validator

from fdai.delivery.azure.llm.redaction_rules import REDACTED, redact
from fdai.shared.contracts.models import ContractBase

_MAX_MESSAGES: Final[int] = 24
_MAX_REQUEST_CHARS: Final[int] = 12_000
_MAX_RESPONSE_CHARS: Final[int] = 6_000
_TRUNCATED: Final[str] = "\n[TRUNCATED]"

_LOGGER = logging.getLogger(__name__)

ModelTraceObserver = Callable[[Mapping[str, object]], None]
_OBSERVERS: list[ModelTraceObserver] = []


def register_model_trace_observer(observer: ModelTraceObserver) -> None:
    """Mirror every completed model-call trace to a best-effort observer.

    The trace is already redacted and bounded. Observers run synchronously on the caller's
    task, so they MUST be cheap and non-blocking; a failure is logged and never raised.
    """
    if observer not in _OBSERVERS:
        _OBSERVERS.append(observer)


def clear_model_trace_observers() -> None:
    """Remove every observer; intended for composition teardown and tests."""
    _OBSERVERS.clear()


def _notify_observers(trace: Mapping[str, object]) -> None:
    for observer in tuple(_OBSERVERS):
        try:
            observer(trace)
        except Exception:
            _LOGGER.warning("model_trace_observer_failed", exc_info=True)


@dataclass(frozen=True, slots=True)
class ModelTraceStart:
    """Sanitized request state and timing for one provider call."""

    started_at: str
    started_monotonic: float
    request: dict[str, object]
    redactions: Counter[str]


class ModelInputMinimizationReceipt(ContractBase):
    """Content-free receipt for one preflight model or embedding sanitization pass."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    boundary: Literal["chat-completions", "responses-input", "embeddings"]
    original_sha256: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    sanitized_sha256: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    content_item_count: int = Field(ge=0)
    transmittable_item_count: int = Field(ge=0)
    transmitted_char_count: int = Field(ge=0)
    redaction_replacement_count: int = Field(ge=0)
    redaction_rule_count: int = Field(ge=0)
    redaction_rules: tuple[str, ...] = ()
    disposition: Literal["transmit", "hold"]
    hold_reason_codes: tuple[str, ...] = ()
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _validate_state(self) -> ModelInputMinimizationReceipt:
        if (self.disposition == "hold") != bool(self.hold_reason_codes):
            raise ValueError("model input minimization receipt hold state is inconsistent")
        if self.redaction_rule_count != len(self.redaction_rules):
            raise ValueError("model input minimization receipt redaction rules are inconsistent")
        if tuple(sorted(set(self.redaction_rules))) != self.redaction_rules:
            raise ValueError(
                "model input minimization receipt redaction rules MUST be unique and sorted"
            )
        if tuple(sorted(set(self.hold_reason_codes))) != self.hold_reason_codes:
            raise ValueError(
                "model input minimization receipt hold reason codes MUST be unique and sorted"
            )
        return self


@dataclass(frozen=True, slots=True)
class PreparedModelMessages:
    """Sanitized provider message list paired with its minimization receipt."""

    messages: tuple[dict[str, Any], ...]
    receipt: ModelInputMinimizationReceipt


@dataclass(frozen=True, slots=True)
class PreparedEmbeddingInput:
    """Sanitized embedding input paired with its minimization receipt."""

    text: str
    receipt: ModelInputMinimizationReceipt


class ModelInputMinimizationError(RuntimeError):
    """The input could not be reduced to an approved provider payload."""

    def __init__(self, receipt: ModelInputMinimizationReceipt) -> None:
        self.receipt = receipt
        reasons = ",".join(receipt.hold_reason_codes)
        super().__init__(f"model input minimization blocked provider transmission: {reasons}")


def start_model_trace(messages: Sequence[Mapping[str, Any]]) -> ModelTraceStart:
    """Capture a bounded sanitized request without retaining provider credentials."""
    sanitized, redactions = _sanitize_messages(messages)
    return ModelTraceStart(
        started_at=_now(),
        started_monotonic=time.monotonic(),
        request={"messages": sanitized, "sha256": _sha256(_canonical(messages))},
        redactions=redactions,
    )


def complete_model_trace(
    start: ModelTraceStart,
    *,
    call_id: str,
    kind: str,
    model: str,
    response_content: str,
    usage: Mapping[str, Any] | None,
) -> dict[str, object]:
    """Return one Console-compatible redacted model-call trace."""
    redacted, response_redactions = _redact(response_content, max_chars=_MAX_RESPONSE_CHARS)
    redactions = start.redactions.copy()
    redactions.update(response_redactions)
    trace: dict[str, object] = {
        "call_id": call_id[:128],
        "kind": kind[:128],
        "model": model[:128],
        "status": "completed",
        "started_at": start.started_at,
        "completed_at": _now(),
        "duration_ms": max(0, int((time.monotonic() - start.started_monotonic) * 1_000)),
        "request": start.request,
        "response": {
            "role": "assistant",
            "content": redacted,
            "sha256": _sha256(response_content),
        },
        "usage": observed_usage(usage),
        "redactions": [
            {"rule": rule, "replacements": count} for rule, count in sorted(redactions.items())
        ],
    }
    _notify_observers(trace)
    return trace


def content_free_model_trace(trace: Mapping[str, object]) -> dict[str, object]:
    """Keep hashes, usage, timing, and redaction counts while dropping model content."""

    request = trace.get("request")
    response = trace.get("response")
    return {
        **trace,
        "content_omitted": True,
        "request": {
            "messages": [],
            "sha256": request.get("sha256") if isinstance(request, Mapping) else None,
        },
        "response": {
            "role": "assistant",
            "content": "",
            "sha256": response.get("sha256") if isinstance(response, Mapping) else None,
        },
    }


def bounded_usage(value: Mapping[str, Any] | None) -> dict[str, int] | None:
    """Keep only measured non-negative provider token counters."""
    if value is None:
        return None
    output = {
        key: item
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance((item := value.get(key)), int) and not isinstance(item, bool) and item >= 0
    }
    return output or None


def observed_usage(value: Mapping[str, Any] | None) -> dict[str, int] | None:
    """Return bounded usage plus the provider's cached prompt-token count, when reported.

    The cached count is the portion of the prompt the provider served from its prompt cache.
    It rides with the call's trace usage and the turn's total so the operator sees how much of
    the input was cached; a missing or malformed detail never invents a count.
    """
    output = bounded_usage(value)
    details = value.get("prompt_tokens_details") if value is not None else None
    cached = details.get("cached_tokens") if isinstance(details, Mapping) else None
    if output is not None and isinstance(cached, int) and not isinstance(cached, bool):
        if cached >= 0:
            output["cached_tokens"] = cached
    return output


def prepare_model_messages(
    messages: Sequence[Mapping[str, Any]],
    *,
    boundary: Literal["chat-completions", "responses-input"] = "chat-completions",
) -> PreparedModelMessages:
    """Redact provider-bound message content and fail closed on unsafe payloads."""

    prepared_messages: list[dict[str, Any]] = []
    redactions: Counter[str] = Counter()
    hold_reasons: set[str] = set()
    content_item_count = 0
    transmittable_item_count = 0
    transmitted_char_count = 0
    for message in messages:
        prepared_message = dict(message)
        role = str(message.get("role", ""))
        if "content" not in message:
            prepared_messages.append(prepared_message)
            continue
        content_item_count += 1
        prepared_content, content_redactions, content_hold_reasons = _sanitize_live_content(
            message["content"]
        )
        hold_reasons.update(content_hold_reasons)
        redactions.update(content_redactions)
        prepared_message["content"] = prepared_content
        prepared_messages.append(prepared_message)
        transmitted_char_count += len(prepared_content)
        if role != "system" and _has_meaningful_text(prepared_content):
            transmittable_item_count += 1
    if content_item_count > 0 and transmittable_item_count == 0:
        hold_reasons.add("insufficient_safe_text")
    receipt = _build_minimization_receipt(
        boundary=boundary,
        original_value=messages,
        sanitized_value=prepared_messages,
        content_item_count=content_item_count,
        transmittable_item_count=transmittable_item_count,
        transmitted_char_count=transmitted_char_count,
        redactions=redactions,
        hold_reasons=hold_reasons,
    )
    if receipt.disposition == "hold":
        raise ModelInputMinimizationError(receipt)
    return PreparedModelMessages(messages=tuple(prepared_messages), receipt=receipt)


def prepare_embedding_input(text: str) -> PreparedEmbeddingInput:
    """Redact provider-bound embedding text and hold fully unsafe payloads."""

    sanitized_text, redactions = _redact(text, max_chars=None)
    hold_reasons: set[str] = set()
    if not _has_meaningful_text(sanitized_text):
        hold_reasons.add("insufficient_safe_text")
    receipt = _build_minimization_receipt(
        boundary="embeddings",
        original_value=text,
        sanitized_value=sanitized_text,
        content_item_count=1,
        transmittable_item_count=1 if not hold_reasons else 0,
        transmitted_char_count=len(sanitized_text),
        redactions=redactions,
        hold_reasons=hold_reasons,
    )
    if receipt.disposition == "hold":
        raise ModelInputMinimizationError(receipt)
    return PreparedEmbeddingInput(text=sanitized_text, receipt=receipt)


def _sanitize_messages(
    messages: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], Counter[str]]:
    output: list[dict[str, str]] = []
    redactions: Counter[str] = Counter()
    remaining = _MAX_REQUEST_CHARS
    for message in messages[:_MAX_MESSAGES]:
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        content = _text_content(message.get("content"), redactions)
        bounded, content_redactions = _redact(content, max_chars=max(0, remaining))
        redactions.update(content_redactions)
        output.append({"role": str(role), "content": bounded})
        remaining = max(0, remaining - len(bounded))
        if remaining == 0:
            break
    if len(messages) > _MAX_MESSAGES:
        redactions["message-limit"] += len(messages) - _MAX_MESSAGES
    return output, redactions


def _text_content(value: Any, redactions: Counter[str]) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        redactions["non-text-content"] += 1
        return "[NON_TEXT_CONTENT_REDACTED]"
    parts: list[str] = []
    for item in value:
        if (
            isinstance(item, Mapping)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ):
            parts.append(str(item["text"]))
        else:
            parts.append("[NON_TEXT_CONTENT_REDACTED]")
            redactions["non-text-content"] += 1
    return "\n".join(parts)


_REDACTED_CACHE_MAX: Final[int] = 128
_REDACTED_CACHE: OrderedDict[tuple[str, int | None], tuple[str, tuple[tuple[str, int], ...]]] = (
    OrderedDict()
)


def _redact(value: str, *, max_chars: int | None) -> tuple[str, Counter[str]]:
    if len(value) >= 1_024:
        key = (value, max_chars)
        cached = _REDACTED_CACHE.get(key)
        if cached is not None:
            _REDACTED_CACHE.move_to_end(key)
            return cached[0], Counter(dict(cached[1]))
        output, redactions = redact(value)
        if max_chars is not None and len(output) > max_chars:
            keep = max(0, max_chars - len(_TRUNCATED))
            output = f"{output[:keep]}{_TRUNCATED}"[:max_chars]
            redactions["character-limit"] += 1
        _REDACTED_CACHE[key] = (output, tuple(redactions.items()))
        while len(_REDACTED_CACHE) > _REDACTED_CACHE_MAX:
            _REDACTED_CACHE.popitem(last=False)
        return output, redactions
    output, redactions = redact(value)
    if max_chars is not None and len(output) > max_chars:
        keep = max(0, max_chars - len(_TRUNCATED))
        output = f"{output[:keep]}{_TRUNCATED}"[:max_chars]
        redactions["character-limit"] += 1
    return output, redactions


def _sanitize_live_content(value: Any) -> tuple[str, Counter[str], set[str]]:
    if isinstance(value, str):
        redacted, redactions = _redact(value, max_chars=None)
        return redacted, redactions, set()
    if isinstance(value, list):
        parts: list[str] = []
        list_redactions: Counter[str] = Counter()
        hold_reasons: set[str] = set()
        for item in value:
            if (
                isinstance(item, Mapping)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                redacted, item_redactions = _redact(str(item["text"]), max_chars=None)
                list_redactions.update(item_redactions)
                parts.append(redacted)
                continue
            hold_reasons.add("non_text_content")
        return "\n".join(parts), list_redactions, hold_reasons
    return "", Counter(), {"non_text_content"}


def _build_minimization_receipt(
    *,
    boundary: Literal["chat-completions", "responses-input", "embeddings"],
    original_value: object,
    sanitized_value: object,
    content_item_count: int,
    transmittable_item_count: int,
    transmitted_char_count: int,
    redactions: Counter[str],
    hold_reasons: set[str],
) -> ModelInputMinimizationReceipt:
    redaction_rules = tuple(sorted(redactions))
    return ModelInputMinimizationReceipt(
        boundary=boundary,
        original_sha256=f"sha256:{_sha256(_canonical(original_value))}",
        sanitized_sha256=f"sha256:{_sha256(_canonical(sanitized_value))}",
        content_item_count=content_item_count,
        transmittable_item_count=transmittable_item_count,
        transmitted_char_count=transmitted_char_count,
        redaction_replacement_count=sum(redactions.values()),
        redaction_rule_count=len(redaction_rules),
        redaction_rules=redaction_rules,
        disposition="hold" if hold_reasons else "transmit",
        hold_reason_codes=tuple(sorted(hold_reasons)),
    )


def _has_meaningful_text(value: str) -> bool:
    candidate = value.replace(REDACTED, "").strip()
    return bool(candidate)


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


__all__ = [
    "ModelInputMinimizationError",
    "ModelInputMinimizationReceipt",
    "ModelTraceObserver",
    "PreparedEmbeddingInput",
    "PreparedModelMessages",
    "bounded_usage",
    "clear_model_trace_observers",
    "complete_model_trace",
    "observed_usage",
    "prepare_embedding_input",
    "prepare_model_messages",
    "register_model_trace_observer",
    "start_model_trace",
]
