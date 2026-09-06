"""One-attempt async structured generation for authority-free conversation."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast

import httpx
from azure.core.exceptions import ClientAuthenticationError
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from fdai.core.conversation.adaptive_prompt import (
    ADAPTIVE_STAGES,
    MAX_ADAPTIVE_SYSTEM_TOKENS,
)
from fdai.core.conversation.model_observation import (
    ConversationModelObservation,
    ConversationModelResponse,
)
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.model_trace import (
    bounded_usage,
    complete_model_trace,
    prepare_model_messages,
    start_model_trace,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_judgment import _strict_response_format
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AdaptiveModelTarget:
    """Resolved transport plus configured model provenance for independence."""

    target: ModelRequestTarget
    publisher: str
    family: str
    structured_output: bool = True

    def __post_init__(self) -> None:
        if any(not text.strip() or len(text) > 128 for text in (self.publisher, self.family)):
            raise ValueError("adaptive model provenance MUST be non-empty and bounded")

    def independent_of(self, other: AdaptiveModelTarget) -> bool:
        """Reject aliases of one deployment or the same configured base model."""

        same_deployment = (
            self.target.endpoint.rstrip("/").casefold(),
            self.target.deployment.casefold(),
        ) == (
            other.target.endpoint.rstrip("/").casefold(),
            other.target.deployment.casefold(),
        )
        same_model = (self.publisher.strip().casefold(), self.family.strip().casefold()) == (
            other.publisher.strip().casefold(),
            other.family.strip().casefold(),
        )
        return not same_deployment and not same_model


@dataclass(frozen=True, slots=True)
class AzureOpenAIAdaptiveModelConfig:
    """Immutable independent bindings and total per-attempt resource ceilings."""

    primary: AdaptiveModelTarget
    reviewer: AdaptiveModelTarget
    escalation: AdaptiveModelTarget | None = None
    timeout_seconds: float = 20.0
    max_tokens: int = 4_096
    max_request_bytes: int = 262_144
    max_response_bytes: int = 65_536
    max_system_tokens: int = MAX_ADAPTIVE_SYSTEM_TOKENS

    def __post_init__(self) -> None:
        for producer in (self.primary, self.escalation):
            if producer is not None and not self.reviewer.independent_of(producer):
                raise ValueError("adaptive review MUST use an independent configured model")
        if isinstance(self.timeout_seconds, bool) or not 0 < self.timeout_seconds <= 120:
            raise ValueError("adaptive timeout_seconds MUST be in (0, 120]")
        for value, upper in (
            (self.max_tokens, 4_096),
            (self.max_request_bytes, 1_048_576),
            (self.max_response_bytes, 262_144),
            (self.max_system_tokens, 32_768),
        ):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError("adaptive request and response budgets MUST be bounded integers")


class AzureOpenAIAdaptiveModel:
    """Use existing Azure transport seams without failover or hidden escalation.

    Every invocation makes at most one provider request. The caller owns the
    turn deadline and permits at most one explicit T2 ``refine`` invocation.
    Provider errors, refusal, malformed output, and deadlines return ``None``;
    external cancellation remains a control-flow signal.
    """

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAIAdaptiveModelConfig,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._config = config

    @property
    def refinement_available(self) -> bool:
        """Whether a separate configured T2 refinement binding is available.

        Availability is not permission: the service must also allow refinement
        under its per-turn policy, budget, and one-refinement limit.
        """

        return self._config.escalation is not None

    async def complete(
        self,
        *,
        stage: str,
        system_prompt: str,
        payload: Mapping[str, object],
        schema: Mapping[str, object],
        escalated: bool = False,
    ) -> ConversationModelResponse | None:
        """Return strict output and measured usage, or a content-free unavailable outcome."""

        if stage not in ADAPTIVE_STAGES or type(escalated) is not bool:
            _unavailable("invalid_stage", "invalid_request")
            return None
        selected = self._select(stage, escalated)
        if selected is None:
            _unavailable(stage, "binding_unavailable")
            return None
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                return await self._request(selected, stage, system_prompt, payload, schema)
        except asyncio.CancelledError:
            raise
        except httpx.HTTPStatusError as exc:
            _unavailable(stage, "provider_status", status=exc.response.status_code)
            return None
        except (TimeoutError, httpx.TimeoutException):
            _unavailable(stage, "deadline")
            return None
        except (
            ValueError,
            TypeError,
            httpx.RequestError,
            SchemaError,
            JsonSchemaValidationError,
            ClientAuthenticationError,
        ):
            _unavailable(stage, "invalid_or_unavailable")
            return None

    def _select(self, stage: str, escalated: bool) -> AdaptiveModelTarget | None:
        if stage in {"review", "verify"}:
            return self._config.reviewer
        if stage == "refine":
            return self._config.escalation if escalated else None
        return None if escalated else self._config.primary

    async def _request(
        self,
        selected: AdaptiveModelTarget,
        stage: str,
        system_prompt: str,
        payload: Mapping[str, object],
        schema: Mapping[str, object],
    ) -> ConversationModelResponse:
        if not system_prompt.strip() or (
            len(system_prompt.encode("utf-8")) > self._config.max_system_tokens
        ):
            raise ValueError("adaptive system prompt is empty or exceeds budget")
        schema_text = _dump_json(dict(schema))
        if len(schema_text.encode("utf-8")) > self._config.max_request_bytes:
            raise ValueError("adaptive schema exceeds request byte budget")
        schema_copy, response_format, validator, strict_validator = _prepared_schema(
            schema_text,
            stage,
            selected.structured_output,
        )
        user_payload: dict[str, object] = {"untrusted_input": dict(payload)}
        if response_format is None:
            user_payload["output_schema"] = schema_copy
        messages = list(
            prepare_model_messages(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": _dump_json(user_payload),
                    },
                ]
            ).messages
        )
        request = selected.target.operation("chat/completions")
        body: dict[str, Any] = {
            "messages": messages,
            **completion_body_params(
                selected.family, temperature=0.0, max_tokens=self._config.max_tokens
            ),
        }
        if response_format is not None:
            body["response_format"] = response_format
        if request.model_body_field is not None:
            body["model"] = request.model_body_field
        encoded = _dump_json(body).encode("utf-8")
        if len(encoded) > self._config.max_request_bytes:
            raise ValueError("adaptive request exceeds byte budget")
        token = await self._identity.get_token(selected.target.auth_audience)
        trace_start = start_model_trace(messages)
        async with self._http.stream(
            "POST",
            request.url,
            params=request.params,
            headers={
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json",
            },
            content=encoded,
            timeout=self._config.timeout_seconds,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > self._config.max_response_bytes:
                    raise ValueError("adaptive response exceeds byte budget")
                raw.extend(chunk)
        envelope = _load_json(bytes(raw))
        proposal, content, usage = _parse_response(envelope)
        validator.validate(proposal)
        if strict_validator is not None:
            strict_validator.validate(proposal)
        trace_call = complete_model_trace(
            trace_start,
            call_id=f"adaptive-{stage}",
            kind=f"adaptive-{stage}",
            model=selected.target.deployment,
            response_content=content,
            usage=usage,
        )
        return ConversationModelResponse(
            proposal=proposal,
            observation=ConversationModelObservation(
                model=selected.target.deployment,
                usage=bounded_usage(usage),
                trace_call=trace_call,
            ),
        )


@lru_cache(maxsize=16)
def _prepared_schema(
    schema_text: str,
    stage: str,
    structured_output: bool,
) -> tuple[
    dict[str, Any], dict[str, Any] | None, Draft202012Validator, Draft202012Validator | None
]:
    """Reuse bounded schema preparation only; no prompt, token, or response is cached."""
    schema = _load_json(schema_text)
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("adaptive output schema MUST describe an object")
    _local_schema_references(schema)
    Draft202012Validator.check_schema(schema)
    response_format = (
        _strict_response_format(schema, name=f"adaptive-{stage}") if structured_output else None
    )
    strict = (
        Draft202012Validator(cast(Mapping[str, Any], response_format["json_schema"])["schema"])
        if response_format is not None
        else None
    )
    return schema, response_format, Draft202012Validator(schema), strict


def _parse_response(value: object) -> tuple[dict[str, object], str, Mapping[str, object] | None]:
    if not isinstance(value, dict):
        raise ValueError("adaptive provider envelope MUST be an object")
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("adaptive provider MUST return exactly one choice")
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
        raise ValueError("adaptive provider output did not finish normally")
    message = choice.get("message")
    if (
        not isinstance(message, dict)
        or message.get("role") != "assistant"
        or message.get("refusal") is not None
        or message.get("tool_calls")
        or message.get("function_call")
        or not isinstance(message.get("content"), str)
    ):
        raise ValueError("adaptive provider output MUST contain only assistant JSON")
    content = message["content"]
    proposal = _load_json(content)
    if not isinstance(proposal, dict):
        raise ValueError("adaptive proposal MUST be an object")
    usage = value.get("usage")
    return proposal, content, usage if isinstance(usage, dict) else None


def _dump_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _load_json(value: str | bytes) -> Any:
    return json.loads(
        value,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("adaptive JSON MUST NOT contain duplicate keys")
        output[key] = value
    return output


def _reject_constant(value: str) -> object:
    raise ValueError("adaptive JSON MUST NOT contain non-finite values")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("adaptive JSON numbers MUST be finite")
    return number


def _local_schema_references(value: object) -> None:
    """Schema validation must never fetch remote references or trust rebased ids."""

    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"$id", "$dynamicRef", "$recursiveRef"}:
                raise ValueError("adaptive schema MUST NOT rebase references")
            if key == "$ref" and (not isinstance(item, str) or not item.startswith("#/")):
                raise ValueError("adaptive schema references MUST be local")
            _local_schema_references(item)
    elif isinstance(value, list):
        for item in value:
            _local_schema_references(item)


def _unavailable(stage: str, reason: str, *, status: int | None = None) -> None:
    _LOGGER.warning(
        "adaptive_model_unavailable",
        extra={"stage": stage, "reason": reason, "provider_status": status},
    )


__all__ = [
    "AdaptiveModelTarget",
    "AzureOpenAIAdaptiveModel",
    "AzureOpenAIAdaptiveModelConfig",
]
